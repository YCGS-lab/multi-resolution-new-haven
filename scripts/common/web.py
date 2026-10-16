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


# region grid-class
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
# endregion grid-class


# region fine-grid
def fine_grid(native_m: float) -> Grid:
    """Grid for data with native pixels of `native_m` ground meters: the native
    size when it is FINE_M or finer, else the native size divided by the
    smallest integer that brings it to FINE_M or below."""
    return Grid(native_m / max(1, math.ceil(native_m / FINE_M - 1e-9)))
# endregion fine-grid


# region web-reproject
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
# endregion web-reproject


# --------------------------------------------------------------------------
# COGs
# --------------------------------------------------------------------------


# region write-cog
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
# endregion write-cog


# --------------------------------------------------------------------------
# Image services (called by the website directly)
# --------------------------------------------------------------------------


# region arcgis-source
def arcgis_source(
    url: str,
    native_m: float,
    bands: list[str] | None = None,
    band_ids: list[int] | None = None,
    raw: bool = False,
    scale: float = 1.0,
    nodata: float | None = None,
    variants: dict[str, dict] | None = None,
) -> dict:
    """An ArcGIS ImageServer, read through exportImage for each website tile.

    raw=False: the server's 8-bit band values as a JPEG (`band_ids` as R, G, B),
               shown as is (render `identity()`).
    raw=True:  float32 values (rendering rule None), named `bands`, multiplied
               by `scale` (e.g. feet to meters); `nodata` is masked.
    native_m: ground pixel size of the source (limits the website's zoom levels).
    variants: per timestep (a key of the product's time list, e.g. "2019"), the
              fields that differ for that timestep, e.g. another service URL:
              {"2019": arcgis_variant(url, native_m, band_ids=...)}.
    """
    s = dict(type="arcgis", url=url.rstrip("/"), raw=raw, res=native_m * EXTENT_VIEW.merc_scale, pixel_m=native_m)
    if raw:
        s.update(bands=bands or ["value"], scale=scale, nodata=nodata)
    else:
        s.update(bands=["r", "g", "b"])
    if band_ids is not None:
        s["band_ids"] = band_ids
    if variants:
        s["variants"] = variants
    return s


def arcgis_variant(url: str, native_m: float, **fields) -> dict:
    """The fields of an arcgis_source that change for one timestep (see arcgis_source's `variants`)."""
    return dict(url=url.rstrip("/"), res=native_m * EXTENT_VIEW.merc_scale, pixel_m=native_m, **fields)
# endregion arcgis-source


# region xyz-source
def xyz_source(
    url: str,
    max_zoom: int,
    attribution: str | None = None,
    tile_size: int = 256,
    smooth: bool = True,
) -> dict:
    """XYZ (slippy map) tiles, {z}/{x}/{y}: map images shown with `identity()`.

    The website picks the zoom level so that map labels come out at about their
    design size (tile_size=512 for "@2x" tiles) and scales the tiles smoothly
    (smooth=False: imagery, drawn with nearest neighbor at native resolution).

    The URL may also hold {time:<name>} placeholders, filled from the selected
    timestep's parameters (see time_spec), and {credential:<name>}, filled
    from the credentials the user entered on the website (never stored in
    the catalog).
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
        smooth=smooth,
    )
# endregion xyz-source


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


# region simple-render-specs
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
# endregion simple-render-specs


# region colormap-spec
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
# endregion colormap-spec


# region categorical-spec
def categorical(band: str, colors: dict[int, str]) -> dict:
    """Class codes -> colors (codes not listed are transparent)."""
    return dict(type="categorical", band=band, colors={str(k): _hex(c) for k, c in colors.items()})
# endregion categorical-spec


# region layer-and-product
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
    **meta,
) -> dict:
    """A menu image: layers drawn bottom to top, plus the text around it.

    native: short description of the native resolution (shown under the title);
            native_by_time={timestep: text} where it changes with the timestep.
    legend: dict(entries=[(color, label), ...], [title, ncol]).
    meta: this product's own time / requires / coverage / min_zoom / native_by_time
          (else the dataset's, see write_spec).
    """
    p = dict(
        title=title,
        subtitle=subtitle,
        source=source,
        native=native,
        landmark_color=_hex(landmark_color),
        layers=layers,
        **meta,
    )
    if legend:
        p["legend"] = dict(
            title=legend.get("title"),
            ncol=legend.get("ncol", 1),
            entries=[dict(color=_hex(c), label=l) for c, l in legend["entries"]],
        )
    return p
# endregion layer-and-product


# region write-spec
def write_spec(dataset: str, sources: dict[str, dict], products: dict[str, dict], meta: dict | None = None) -> Path:
    """Write website/image-data/<dataset>.json.

    meta: what every product of the dataset shares (a product's own keys win):
    dict(time=time_spec(...), requires=..., coverage=coverage(...), min_zoom=...); see dataset_meta.
    """
    for name, p in products.items():
        for l in p["layers"]:
            assert l["source"] in sources, f"{name}: unknown source {l['source']}"
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / f"{dataset}.json"
    spec = dict(dataset=dataset, meta=meta or {}, sources=sources, products=products)
    path.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    print(f"  wrote {path.relative_to(config.REPO)}: {', '.join(products)}")
    return path
# endregion write-spec


# --------------------------------------------------------------------------
# Live sources: data services the website queries for the selected timestep
# --------------------------------------------------------------------------

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_DATA = "https://planetarycomputer.microsoft.com/api/data/v1"


# region pc-mosaic-source
def pc_mosaic_source(
    collection: str,
    bands: dict[str, str],
    native_m: float,
    fmt: str = "npy",
    scale: dict[str, float] | None = None,
    offset: dict[str, float] | None = None,
    nodata: float | None = None,
    query: list[dict] | None = None,
    max_zoom: int | None = None,
) -> dict:
    """A Planetary Computer STAC collection, mosaicked per timestep by its data API.

    For the selected timestep (or start / end window), the website registers a
    mosaic search (POST {PC_DATA}/mosaic/register: the collection, the window,
    the user's filters, e.g. eo:cloud_cover, plus `query`, CQL2-JSON
    conditions) and reads its tiles:
      fmt="npy": raw values of the assets the render spec needs (named by
                 `bands`: band -> "asset" or "asset|band index"), times
                 `scale` plus `offset` per band (e.g. Landsat Collection 2
                 scale factors); `nodata` = no data
      fmt="png": the assets as an 8-bit RGB image, shown with identity()
    """
    s = dict(
        type="pc-mosaic",
        stac=PC_STAC,
        api=PC_DATA,
        collection=collection,
        bands=list(bands),
        assets=bands,
        format=fmt,
        res=native_m * EXTENT_VIEW.merc_scale,
        pixel_m=native_m,
        query=query or [],
    )
    if scale:
        s["scale"] = scale
    if offset:
        s["offset"] = offset
    if nodata is not None:
        s["nodata"] = nodata
    if max_zoom is not None:
        s["max_zoom"] = max_zoom
    return s
# endregion pc-mosaic-source


# region titiler-cmr-source
def titiler_cmr_source(
    concept_id: str,
    variables: list[str],
    native_m: float,
    group: str | None = None,
    derive: dict[str, str] | None = None,
    attribution: str | None = None,
    service: str = "titiler_cmr",
) -> dict:
    """A NASA Earthdata (CMR) collection read by titiler-cmr's xarray backend.

    titiler-cmr runs next to the data (S3 in us-west-2) and opens the granules
    of the selected window on the fly. The website calls the service named
    `service` in env.json: "titiler_cmr" is the public NASA VEDA deployment
    (works from anywhere); "earthdata_tiler" is a deployment of the same API
    with Earthdata S3 credentials for the DAACs the public one cannot read,
    run alongside the website in AWS (cloud-only, see requires_cloud). Tiles
    are raw values of `variables` (NPY) mosaicked over the selected window;
    `derive` adds bands computed from them (name -> expression, e.g.
    "10 * log10(HHHH)").
    """
    s = dict(
        type="titiler-cmr",
        service=service,
        concept_id=concept_id,
        variables=variables,
        bands=[*variables, *(derive or {})],
        res=native_m * EXTENT_VIEW.merc_scale,
        pixel_m=native_m,
    )
    if group:
        s["group"] = group
    if derive:
        s["derive"] = derive
    if attribution:
        s["attribution"] = attribution
    return s
# endregion titiler-cmr-source


# region cds-source
def cds_source(dataset: str, variable: str, band: str, native_deg: float, offset: float = 0.0, max_area_deg: float = 12.0) -> dict:
    """A Copernicus Climate Data Store dataset on a regular lat / lon grid
    (e.g. ERA5-Land), requested by the website with the user's CDS API key
    for the selected hour(s) over the area in view (at most `max_area_deg` on
    a side), as GRIB; values + `offset` (e.g. -273.15 for K to deg C) become
    band `band`."""
    return dict(
        type="cds",
        api="https://cds.climate.copernicus.eu/api",
        dataset=dataset,
        variable=variable,
        bands=[band],
        offset=offset,
        grid_deg=native_deg,
        max_area_deg=max_area_deg,
        res=native_deg * 111320 * EXTENT_VIEW.merc_scale,
        pixel_m=native_deg * 111320,
        credential="cds",
    )
# endregion cds-source


# --------------------------------------------------------------------------
# Time, requirements, coverage
# --------------------------------------------------------------------------


# region time-spec
def time_spec(
    step: str,
    availability: dict,
    label: str = "Date",
    widget: str = "auto",
    window: dict | None = None,
    filters: list[dict] | None = None,
) -> dict:
    """How a dataset's timesteps are listed and picked on the website.

    step: "year", "month", "day", "hour" or "time" (any time of day): what
          one timestep is, and its key: "2023", "2026-07", "2026-07-20",
          "2026-07-20T14:00Z" (hour and time).
    availability: where the list of timesteps comes from (avail_* below);
          the website asks for the area in view, so it can say when a
          timestep has no data there.
    widget: "auto" (a drop-down for a few timesteps, a calendar for many),
          "list" or "calendar".
    window: window_spec(...) if the user may pick an end date too (the
          images in between are mosaicked); else None.
    filters: filter_range(...) / ... conditions on the images (e.g. cloud cover).
    The default is the latest timestep with data in view.
    """
    assert step in ("year", "month", "day", "hour", "time"), step
    t = dict(step=step, availability=availability, label=label, widget=widget)
    if window:
        t["window"] = window
    if filters:
        t["filters"] = filters
    return t


def avail_list(values: list[str], labels: dict[str, str] | None = None, params: dict[str, dict] | None = None) -> dict:
    """A fixed list of timesteps (keys as in time_spec), with optional labels
    and URL parameters per timestep."""
    a = dict(type="list", values=sorted(values))
    if labels:
        a["labels"] = labels
    if params:
        a["params"] = params
    return a


def avail_stac(source: str, max_items: int = 4000) -> dict:
    """Timesteps with STAC items intersecting the view, from the search API of
    a pc_mosaic_source (its collection and query); the items' properties
    used by the filters (e.g. eo:cloud_cover) come along."""
    return dict(type="stac", source=source, max_items=max_items)


def avail_cmr(concept_id: str, max_items: int = 2000) -> dict:
    """Timesteps with CMR granules intersecting the view (CMR search, public)."""
    return dict(type="cmr", concept_id=concept_id, max_items=max_items)


def avail_planet(prefix: str = "global_monthly_", suffix: str = "_mosaic") -> dict:
    """Monthly Planet basemaps the user's API key can read (Planet Basemaps API):
    mosaics named <prefix>YYYY_MM<suffix>; the timestep's `mosaic` parameter is the name."""
    return dict(type="planet", prefix=prefix, suffix=suffix, credential="planet")


def avail_hourly(start: str, lag_days: int) -> dict:
    """Every hour from `start` (YYYY-MM-DD) until `lag_days` before today (e.g. a reanalysis)."""
    return dict(type="hourly", start=start, lag_days=lag_days)


def window_spec(max_days: int, options: list[dict] | None = None, label: str = "End date") -> dict:
    """An end date may be picked, up to max_days after the start; `options`
    (option(...)) say how the images in the window are combined."""
    return dict(max_days=max_days, options=options or [], label=label)


def option(id: str, label: str, choices: list[tuple[str, str]], default: str, help: str | None = None) -> dict:
    """An advanced option: one of `choices` ((value, label) pairs)."""
    o = dict(id=id, label=label, choices=[dict(value=v, label=l) for v, l in choices], default=default)
    if help:
        o["help"] = help
    return o


def filter_range(id: str, label: str, prop: str, lo: float, hi: float, default: float, step: float = 1, unit: str = "") -> dict:
    """Keep images whose property `prop` is at most the user's value (lo..hi; default = all)."""
    return dict(id=id, type="max", label=label, property=prop, min=lo, max=hi, default=default, step=step, unit=unit)
# endregion time-spec


# region requirements
def requires_credential(name: str) -> dict:
    """The dataset needs a credential the user enters on the website ("planet", "cds")."""
    return dict(credential=name)


def requires_cloud(reason: str, service: str | None = None) -> dict:
    """The dataset is only read in the cloud deployment (e.g. NASA data in S3,
    through a tiler next to it), and only if env.json names `service` there."""
    r = dict(cloud=True, reason=reason)
    if service:
        r["service"] = service
    return r


def coverage(west: float, south: float, east: float, north: float, name: str) -> dict:
    """Where a dataset has data (lon / lat box); outside it the website says so instead of drawing."""
    return dict(bbox=[west, south, east, north], name=name)


CONNECTICUT = coverage(-73.73, 40.95, -71.78, 42.06, "Connecticut")
CONUS = coverage(-125.0, 24.4, -66.9, 49.5, "the contiguous United States")
# endregion requirements


def snapshot_time(key: str, step: str, label: str = "Date") -> dict:
    """A dataset stored locally for one timestep only (a COG from create-cog.py):
    the website shows the timestep, without choices."""
    return time_spec(step, avail_list([key]), label=label, widget="list")
