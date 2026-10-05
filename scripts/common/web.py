"""Image data and render specs for the website (website/image-data/).

The website draws every image itself, tile by tile, from either

  - a local Cloud-Optimized GeoTIFF (COG) of real values (temperature,
    elevation, reflectance, ...) written by a dataset's create-cog.py, or
  - an image service it calls directly (ArcGIS ImageServer exportImage, XYZ
    tiles), declared by a dataset's website-layers.py,

and colors the values with a *render spec* (band combination, value range,
colormap, hillshade, ...). Each script writes website/image-data/<dataset>.json:

    {"dataset": ..., "sources": {name: source}, "products": {product: product}}

and scripts/website/build_catalog.py gathers these into website/catalog.json.

All COGs are on Web Mercator (EPSG:3857) grids covering the Greater New Haven
extent, so the website never reprojects. Grids are given by their ground pixel
size at the extent center (`grid(pixel_m)`).

Compression: float data use LERC (lossy, with an absolute max error chosen
per dataset, plus deflate); 8-bit imagery uses JPEG (band-interleaved, so
the website's decoder gets plain RGB, not YCbCr); categorical data use
lossless DEFLATE. Float nodata is stored as NODATA (-9999), not NaN, because
the website's LERC decoder ignores LERC's validity mask.
"""

import json
import math
import re
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.crs import CRS as RioCRS
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject as rio_reproject

from . import config
from .views import CRS, VIEWS

WEB_DATA = config.REPO / "website" / "image-data"
EXTENT_VIEW = VIEWS["greater"]
NODATA = -9999.0
# Coarse grids are stored on a finer grid (nearest neighbor) so that each
# native pixel keeps its true footprint (to within FINE_M / 2) after reprojection.
FINE_M = 30.0


# --------------------------------------------------------------------------
# Grids and reprojection
# --------------------------------------------------------------------------


class Grid:
    """A north-up EPSG:3857 grid covering the website extent."""

    def __init__(self, pixel_m: float, pad_px: int = 0):
        """`pixel_m`: ground size of a pixel at the extent center (m). The grid
        is aligned to multiples of its Mercator pixel size and covers the
        extent (plus `pad_px` pixels on each side)."""
        self.pixel_m = pixel_m
        self.res = pixel_m * EXTENT_VIEW.merc_scale  # EPSG:3857 units per pixel
        xmin, ymin, xmax, ymax = EXTENT_VIEW.bounds
        r = self.res
        self.x0 = (math.floor(xmin / r) - pad_px) * r
        self.y1 = (math.ceil(ymax / r) + pad_px) * r
        self.width = int(math.ceil(xmax / r) + pad_px - math.floor(xmin / r) + pad_px)
        self.height = int(math.ceil(ymax / r) + pad_px - math.floor(ymin / r) + pad_px)

    @property
    def transform(self) -> Affine:
        return Affine(self.res, 0, self.x0, 0, -self.res, self.y1)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y1 - self.height * self.res, self.x0 + self.width * self.res, self.y1)

    def bounds_in(self, crs, pad_m: float = 0.0):
        """Grid bounds (padded by `pad_m` ground meters) in another CRS."""
        from rasterio.warp import transform_bounds

        p = pad_m * EXTENT_VIEW.merc_scale
        xmin, ymin, xmax, ymax = self.bounds
        return transform_bounds(CRS, crs, xmin - p, ymin - p, xmax + p, ymax + p, densify_pts=51)

    def __repr__(self):
        return f"Grid({self.pixel_m:g} m: {self.width}x{self.height} px, {self.res:.4f} EPSG:3857 units/px)"


def fine_grid(native_m: float) -> Grid:
    """Grid for data with native pixels of `native_m` ground meters: the native
    size when it is FINE_M or finer, else the native size divided by the
    smallest integer that brings it to FINE_M or below."""
    return Grid(native_m / max(1, math.ceil(native_m / FINE_M - 1e-9)))


def reproject(src, src_transform, src_crs, grid: Grid, resampling: str = "nearest", src_nodata=None) -> np.ndarray:
    """Resample a 2-D or (bands, rows, cols) array onto `grid`; NaN = no data."""
    src = np.asarray(src, dtype="float32")
    squeeze = src.ndim == 2
    if squeeze:
        src = src[None]
    if src_nodata is not None and not (isinstance(src_nodata, float) and math.isnan(src_nodata)):
        src = np.where(src == src_nodata, np.nan, src)
    dst = np.full((src.shape[0], *grid.shape), np.nan, dtype="float32")
    rio_reproject(
        source=src,
        destination=dst,
        src_transform=src_transform,
        src_crs=RioCRS.from_user_input(src_crs),
        src_nodata=np.nan,
        dst_transform=grid.transform,
        dst_crs=CRS,
        dst_nodata=np.nan,
        resampling=Resampling[resampling],
    )
    return dst[0] if squeeze else dst


# --------------------------------------------------------------------------
# COGs
# --------------------------------------------------------------------------


def write_cog(
    name: str,
    data: np.ndarray,
    grid: Grid,
    bands: list[str],
    kind: str = "float",
    max_z_error: float | None = None,
    quality: int = 90,
    overview_resampling: str | None = None,
    nodata: int | None = 0,
) -> dict:
    """Write website/image-data/<name>.tif and return its source spec.

    data: (bands, rows, cols) on `grid` (NaN = no data for floats).
    kind:
      "float":       float32, LERC_DEFLATE with absolute error `max_z_error`
      "jpeg":        uint8 imagery, JPEG `quality`, band-interleaved
      "categorical": uint8 class codes (`nodata`, default 0, = no data), lossless DEFLATE
    Band names must be valid JavaScript identifiers (used in expressions).
    """
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[None]
    assert data.shape[1:] == grid.shape, f"data {data.shape[1:]} != grid {grid.shape}"
    assert len(bands) == data.shape[0] and all(re.fullmatch(r"[A-Za-z_]\w*", b) for b in bands), bands
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / f"{name}.tif"
    profile = dict(
        driver="COG",
        width=grid.width,
        height=grid.height,
        count=data.shape[0],
        crs=CRS,
        transform=grid.transform,
        blocksize=512,
        BIGTIFF="IF_SAFER",
    )
    if kind == "float":
        assert max_z_error is not None, "float COGs need max_z_error"
        out = np.where(np.isfinite(data), data, NODATA).astype("float32")
        profile.update(
            dtype="float32",
            nodata=NODATA,
            compress="LERC_DEFLATE",
            max_z_error=max_z_error,
            overview_resampling=overview_resampling or "average",
        )
    elif kind == "jpeg":
        out = data.astype("uint8")
        profile.update(
            dtype="uint8",
            compress="JPEG",
            quality=quality,
            interleave="band",
            overview_resampling=overview_resampling or "average",
        )
    elif kind == "categorical":
        out = data.astype("uint8")
        profile.update(dtype="uint8", nodata=nodata, compress="DEFLATE", overview_resampling=overview_resampling or "mode")
    else:
        raise ValueError(kind)
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(out)
        ds.descriptions = tuple(bands)
    size = path.stat().st_size
    print(f"  wrote {path.relative_to(config.REPO)} ({grid}, {len(bands)} bands, {size / 1e6:.1f} MB)")
    source = dict(
        type="cog",
        url=f"image-data/{path.name}",
        bands=bands,
        bounds=list(grid.bounds),
        width=grid.width,
        height=grid.height,
        res=grid.res,
        pixel_m=grid.pixel_m,
    )
    if kind == "float":
        source["nodata"] = NODATA
    elif kind == "categorical" and nodata is not None:
        source["nodata"] = nodata
    return source


# --------------------------------------------------------------------------
# Image services (called by the website directly)
# --------------------------------------------------------------------------


def arcgis_source(
    url: str,
    native_m: float,
    bands: list[str] | None = None,
    band_ids: list[int] | None = None,
    raw: bool = False,
    scale: float = 1.0,
    nodata: float | None = None,
) -> dict:
    """An ArcGIS ImageServer, read through exportImage for each website tile.

    raw=False: the server's 8-bit band values as a JPEG (`band_ids` as R, G, B),
               shown as is (render `identity()`).
    raw=True:  float32 values (rendering rule None), named `bands`, multiplied
               by `scale` (e.g. feet to meters); `nodata` is masked.
    native_m: ground pixel size of the source (limits the website's zoom levels).
    """
    s = dict(type="arcgis", url=url.rstrip("/"), raw=raw, res=native_m * EXTENT_VIEW.merc_scale, pixel_m=native_m)
    if raw:
        s.update(bands=bands or ["value"], scale=scale, nodata=nodata)
    else:
        s.update(bands=["r", "g", "b"])
    if band_ids is not None:
        s["band_ids"] = band_ids
    return s


def xyz_source(url: str, max_zoom: int, attribution: str | None = None, tile_size: int = 256) -> dict:
    """XYZ (slippy map) tiles, {z}/{x}/{y}: map images shown with `identity()`.

    The website picks the zoom level so that map labels come out at about their
    design size (tile_size=512 for "@2x" tiles) and scales the tiles smoothly.
    """
    native_res = 2 * math.pi * 6378137.0 / (tile_size * 2**max_zoom)
    return dict(
        type="xyz",
        url=url,
        max_zoom=max_zoom,
        tile_size=tile_size,
        bands=["r", "g", "b"],
        res=native_res,
        pixel_m=native_res / EXTENT_VIEW.merc_scale,
        attribution=attribution,
        smooth=True,
    )


# --------------------------------------------------------------------------
# Render specs: how a layer's values become colors
# --------------------------------------------------------------------------


def _hex(color) -> str:
    return mcolors.to_hex(color, keep_alpha=mcolors.to_rgba(color)[3] < 1)


def mathtext_to_unicode(s: str) -> str:
    """'nW cm$^{-2}$ sr$^{-1}$' -> 'nW cm⁻² sr⁻¹' (simple super/subscripts only)."""
    sup = str.maketrans("0123456789-+=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺⁼⁽⁾ⁿ")
    sub = str.maketrans("0123456789-+=()", "₀₁₂₃₄₅₆₇₈₉₋₊₌₍₎")
    s = re.sub(r"\$\^\{?([^}$]*)\}?\$", lambda m: m.group(1).translate(sup), s)
    s = re.sub(r"\$_\{?([^}$]*)\}?\$", lambda m: m.group(1).translate(sub), s)
    return s.replace("$", "")


def _value(band: str | None, expr: str | None) -> dict:
    assert (band is None) != (expr is None), "give exactly one of band, expr"
    return dict(band=band) if band is not None else dict(expr=expr)


def identity(desaturate: float = 0.0, lighten: float = 0.0) -> dict:
    """Show an RGB image as is (optionally desaturated / lightened, as for a basemap)."""
    r = dict(type="identity")
    if desaturate or lighten:
        r.update(desaturate=desaturate, lighten=lighten)
    return r


def channel(band: str | None = None, lo: float = 0.0, hi: float = 1.0, gamma: float = 1.0, expr: str | None = None) -> dict:
    """One RGB channel: linear stretch of a band (or expression of bands) from lo..hi to 0..1, then ^(1/gamma)."""
    return dict(**_value(band, expr), min=float(lo), max=float(hi), gamma=float(gamma))


def rgb(r: dict, g: dict, b: dict) -> dict:
    return dict(type="rgb", channels=[r, g, b])


def colormap(
    cmap,
    norm,
    label: str | None = None,
    band: str | None = None,
    expr: str | None = None,
    extend: str = "neither",
    ticks=None,
    gamma: float = 1.0,
    hillshade: bool = False,
    shade: dict | None = None,
) -> dict:
    """Color a band (or expression) with a matplotlib colormap and norm (Normalize or LogNorm).

    hillshade=True colors the hillshade (0-1) of the band instead of the band.
    shade=dict(band=..., strength=...) multiplies the colors by that band's hillshade
    (as render.blend_hillshade); with precomputed=True the band already is a
    hillshade (0-1). `label` makes the website show a colorbar.
    """
    cmap = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap
    if isinstance(norm, mcolors.LogNorm):
        scale = "log"
    elif type(norm) is mcolors.Normalize:
        scale = "linear"
    else:
        raise ValueError(f"unsupported norm {type(norm).__name__}")
    r = dict(
        type="colormap",
        **_value(band, expr),
        vmin=float(norm.vmin),
        vmax=float(norm.vmax),
        scale=scale,
        gamma=float(gamma),
        colors=[_hex(c) for c in cmap(np.linspace(0, 1, 256))],
        under=_hex(cmap.get_under()),
        over=_hex(cmap.get_over()),
        extend=extend,
    )
    if label:
        r["label"] = mathtext_to_unicode(label)
    if ticks is not None:
        r["ticks"] = [float(t) for t in ticks]
    if hillshade:
        r["hillshade"] = True
    if shade:
        r["shade"] = dict(band=shade["band"], strength=float(shade.get("strength", 0.5)))
        if shade.get("precomputed"):
            r["shade"]["precomputed"] = True
    return r


def categorical(band: str, colors: dict[int, str]) -> dict:
    """Class codes -> colors (codes not listed are transparent)."""
    return dict(type="categorical", band=band, colors={str(k): _hex(c) for k, c in colors.items()})


def layer(source: str, render: dict, dilate_px: int = 0) -> dict:
    """One layer of a product: a source (name in this dataset's sources) and its render spec.

    dilate_px: grow data pixels by this many screen pixels (keeps sparse
    points, e.g. ICESat-2 footprints, visible when zoomed out).
    """
    out = dict(source=source, render=render)
    if dilate_px:
        out["dilate_px"] = int(dilate_px)
    return out


def product(
    title: str,
    layers: list[dict],
    subtitle: str | None = None,
    source: str | None = None,
    native: str | None = None,
    legend: dict | None = None,
    landmark_color: str = "white",
) -> dict:
    """A menu image: layers drawn bottom to top, plus the text around it.

    native: short description of the native resolution (shown under the title).
    legend: dict(entries=[(color, label), ...], [title, ncol]).
    """
    p = dict(
        title=title,
        subtitle=subtitle,
        source=source,
        native=native,
        landmark_color=_hex(landmark_color),
        layers=layers,
    )
    if legend:
        p["legend"] = dict(
            title=legend.get("title"),
            ncol=legend.get("ncol", 1),
            entries=[dict(color=_hex(c), label=l) for c, l in legend["entries"]],
        )
    return p


def write_spec(dataset: str, sources: dict[str, dict], products: dict[str, dict]) -> Path:
    """Write website/image-data/<dataset>.json."""
    for name, p in products.items():
        for l in p["layers"]:
            assert l["source"] in sources, f"{name}: unknown source {l['source']}"
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / f"{dataset}.json"
    path.write_text(json.dumps(dict(dataset=dataset, sources=sources, products=products), indent=1, ensure_ascii=False) + "\n")
    print(f"  wrote {path.relative_to(config.REPO)}: {', '.join(products)}")
    return path
