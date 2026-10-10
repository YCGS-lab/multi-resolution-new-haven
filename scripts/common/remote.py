"""Fetch imagery for a view from tile / image services.

All functions return arrays already on the view's pixel grid:
  - fetch_xyz:            XYZ (slippy map) tiles, e.g. OSM, Planet basemaps
  - arcgis_export_image:  ArcGIS ImageServer exportImage (rendered or raw values)
  - wms_getmap:           OGC WMS GetMap, e.g. NASA GIBS
"""

import io
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .views import CRS, View

USER_AGENT = "multi-resolution-new-haven/0.1 (Yale research visualization)"
EARTH_CIRCUMFERENCE = 2 * math.pi * 6378137.0
ORIGIN = EARTH_CIRCUMFERENCE / 2


# region session
def session(headers: dict | None = None, auth=None) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.headers["User-Agent"] = USER_AGENT
    if headers:
        s.headers.update(headers)
    s.auth = auth
    return s
# endregion session


def _chunks(view: View, max_size: int):
    """Split the view grid into windows no larger than max_size on a side.

    Yields (row0, col0, height, width, bounds_3857).
    """
    t = view.transform
    for r0 in range(0, view.height_px, max_size):
        for c0 in range(0, view.width_px, max_size):
            h = min(max_size, view.height_px - r0)
            w = min(max_size, view.width_px - c0)
            xmin, ymax = t * (c0, r0)
            xmax, ymin = t * (c0 + w, r0 + h)
            yield r0, c0, h, w, (xmin, ymin, xmax, ymax)


def _read_image_bytes(content: bytes) -> np.ndarray:
    """Decode an image response (GeoTIFF/PNG/JPEG) to (bands, h, w)."""
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        with MemoryFile(content) as mf, mf.open() as ds:
            arr = ds.read()
            if ds.nodata is not None and np.issubdtype(arr.dtype, np.floating):
                arr = np.where(arr == ds.nodata, np.nan, arr)
            return arr
    img = np.asarray(Image.open(io.BytesIO(content)))
    return img[None] if img.ndim == 2 else np.moveaxis(img, -1, 0)


# --------------------------------------------------------------------------
# XYZ tiles
# --------------------------------------------------------------------------


def tile_pixel_size(z: int, tile_size: int = 256) -> float:
    """Web Mercator meters per tile pixel at zoom z."""
    return EARTH_CIRCUMFERENCE / (tile_size * 2**z)


def auto_zoom(view: View, max_zoom: int = 19, tile_size: int = 256) -> int:
    """Smallest zoom whose tile pixels are at least as fine as the view's pixels."""
    target = view.pixel_size_m * view.merc_scale
    z = math.ceil(math.log2(EARTH_CIRCUMFERENCE / (tile_size * target)))
    return max(0, min(max_zoom, z))


# region fetch-xyz
def fetch_xyz(
    url_template: str,
    view: View,
    zoom: int | None = None,
    max_zoom: int = 19,
    tile_size: int = 256,
    sess: requests.Session | None = None,
    resampling: str = "bilinear",
    workers: int = 8,
) -> np.ndarray:
    """Mosaic XYZ tiles ({z}/{x}/{y} placeholders) and resample to the view grid.

    Returns RGBA uint8 (h, w, 4); missing tiles are transparent.
    """
    sess = sess or session()
    z = zoom if zoom is not None else auto_zoom(view, max_zoom, tile_size)
    n = 2**z
    span = EARTH_CIRCUMFERENCE / n
    xmin, ymin, xmax, ymax = view.bounds
    tx0, tx1 = int((xmin + ORIGIN) // span), int((xmax + ORIGIN) // span)
    ty0, ty1 = int((ORIGIN - ymax) // span), int((ORIGIN - ymin) // span)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    mosaic = np.zeros((4, ny * tile_size, nx * tile_size), dtype="uint8")

    def get(tx, ty):
        r = sess.get(url_template.format(z=z, x=tx, y=ty), timeout=60)
        if r.status_code == 404:
            return tx, ty, None
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        if img.size != (tile_size, tile_size):
            img = img.resize((tile_size, tile_size), Image.BILINEAR)
        return tx, ty, np.moveaxis(np.asarray(img), -1, 0)

    jobs = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    print(f"  fetching {len(jobs)} tiles at z={z}")
    with ThreadPoolExecutor(workers) as pool:
        for tx, ty, tile in pool.map(lambda j: get(*j), jobs):
            if tile is not None:
                r0, c0 = (ty - ty0) * tile_size, (tx - tx0) * tile_size
                mosaic[:, r0 : r0 + tile_size, c0 : c0 + tile_size] = tile

    src_transform = from_bounds(
        tx0 * span - ORIGIN, ORIGIN - (ty1 + 1) * span, (tx1 + 1) * span - ORIGIN, ORIGIN - ty0 * span,
        mosaic.shape[2], mosaic.shape[1],
    )  # fmt: skip
    out = np.zeros((4, *view.shape), dtype="uint8")
    reproject(
        mosaic,
        out,
        src_transform=src_transform,
        src_crs=CRS,
        dst_transform=view.transform,
        dst_crs=CRS,
        resampling=Resampling[resampling],
    )
    return np.moveaxis(out, 0, -1)
# endregion fetch-xyz


OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "Basemap © OpenStreetMap contributors"


def fetch_osm(view: View, zoom: int | None = None) -> np.ndarray:
    """OpenStreetMap standard tiles for the view (RGBA uint8)."""
    return fetch_xyz(OSM_URL, view, zoom=zoom, max_zoom=19, workers=2)


# --------------------------------------------------------------------------
# ArcGIS ImageServer
# --------------------------------------------------------------------------


# region fetch-chunks
def _fetch_chunks(view: View, max_size: int, workers: int, fetch) -> np.ndarray:
    """Run fetch(h, w, bounds) -> (bands, h, w) over view chunks; assemble."""
    chunks = list(_chunks(view, max_size))
    with ThreadPoolExecutor(workers) as pool:
        arrs = list(pool.map(lambda c: fetch(c[2], c[3], c[4]), chunks))
    a0 = arrs[0]
    dtype = "float32" if np.issubdtype(a0.dtype, np.floating) else a0.dtype
    out = np.zeros((a0.shape[0], *view.shape), dtype=dtype)
    for (r0, c0, h, w, _), arr in zip(chunks, arrs):
        if arr.shape[1:] != (h, w):
            raise RuntimeError(f"service returned {arr.shape[1:]}, expected {(h, w)}")
        out[:, r0 : r0 + h, c0 : c0 + w] = arr
    print(f"  fetched {len(chunks)} chunks")
    return out
# endregion fetch-chunks


# region arcgis-export-image
def arcgis_export_image(
    service_url: str,
    view: View,
    fmt: str = "tiff",
    pixel_type: str | None = None,
    rendering_rule: dict | str | None = None,
    band_ids: list[int] | None = None,
    interpolation: str = "RSP_BilinearInterpolation",
    nodata=None,
    max_size: int = 1024,
    workers: int = 4,
    extra_params: dict | None = None,
    sess: requests.Session | None = None,
) -> np.ndarray:
    """Call `<service_url>/exportImage` for the view in EPSG:3857, in chunks.

    Returns (bands, h, w); float output has NaN for nodata. For raw values use
    fmt="tiff" with e.g. pixel_type="F32" and rendering_rule={"rasterFunction": "None"};
    for rendered imagery use fmt="png"/"jpg". Large single requests tend to
    time out (HTTP 504), hence the small default chunk size.
    """
    import json as _json

    sess = sess or session()
    url = service_url.rstrip("/") + "/exportImage"

    def fetch(h, w, b):
        params = {
            "bbox": ",".join(f"{v:.3f}" for v in b),
            "bboxSR": 3857,
            "imageSR": 3857,
            "size": f"{w},{h}",
            "format": fmt,
            "interpolation": interpolation,
            "f": "image",
        }
        if pixel_type:
            params["pixelType"] = pixel_type
        if rendering_rule is not None:
            params["renderingRule"] = rendering_rule if isinstance(rendering_rule, str) else _json.dumps(rendering_rule)
        if band_ids is not None:
            params["bandIds"] = ",".join(map(str, band_ids))
        if nodata is not None:
            params["noData"] = nodata
        params.update(extra_params or {})
        r = sess.get(url, params=params, timeout=300)
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith(("application/json", "text/")):
            raise RuntimeError(f"exportImage error: {r.text[:500]}")
        return _read_image_bytes(r.content)

    return _fetch_chunks(view, max_size, workers, fetch)
# endregion arcgis-export-image


# --------------------------------------------------------------------------
# WMS
# --------------------------------------------------------------------------

GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi"


def wms_getmap(
    url: str,
    layer: str,
    view: View,
    time: str | None = None,
    fmt: str = "image/png",
    styles: str = "",
    max_size: int = 2048,
    workers: int = 4,
    extra_params: dict | None = None,
    sess: requests.Session | None = None,
) -> np.ndarray:
    """WMS 1.3.0 GetMap for the view in EPSG:3857. Returns (bands, h, w)."""
    sess = sess or session()

    def fetch(h, w, b):
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": layer,
            "STYLES": styles,
            "CRS": "EPSG:3857",
            "BBOX": ",".join(f"{v:.3f}" for v in b),
            "WIDTH": w,
            "HEIGHT": h,
            "FORMAT": fmt,
            "TRANSPARENT": "TRUE",
        }
        if time:
            params["TIME"] = time
        params.update(extra_params or {})
        r = sess.get(url, params=params, timeout=300)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            raise RuntimeError(f"GetMap error: {r.text[:500]}")
        return _read_image_bytes(r.content)

    return _fetch_chunks(view, max_size, workers, fetch)
