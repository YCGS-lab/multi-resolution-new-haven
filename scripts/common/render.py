"""Put data onto a view's pixel grid and write data-only + labeled figures.

Typical use:

    grid = render.reproject_to_view(arr, transform, crs, view)   # NaN = nodata
    img = render.colorize(grid, "inferno", vmin, vmax)            # RGBA uint8
    render.save_figures(img, view, "dataset", "product", title=..., colorbar=...)

Data are subset to (at least) the view bounds, then resampled onto the view's
3840x2160 Web Mercator grid. Coarse data are upsampled with nearest neighbor,
so each native pixel shows up as a block with its true footprint, and pixels
straddling the view edge are cut off by the image frame ("crop the image, not
the data"). Fine data are downsampled by averaging.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, Rectangle
from PIL import Image
from pyproj import Transformer
from rasterio.crs import CRS as RioCRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

from . import config
from .views import CRS, View, load_landmarks

DPI = 200
NODATA_FACE = "#d0d0d0"  # shown behind transparent (nodata) pixels in labeled figures


# --------------------------------------------------------------------------
# Resampling onto the view grid
# --------------------------------------------------------------------------


def native_pixel_size_m(src_transform, src_crs, view: View) -> float:
    """Approximate ground size (m) of one source pixel near the view center."""
    to_src = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
    to_merc = Transformer.from_crs(src_crs, CRS, always_xy=True)
    x, y = to_src.transform(view.lon, view.lat)
    a, e = src_transform.a, src_transform.e
    x0, y0 = to_merc.transform(x, y)
    x1, _ = to_merc.transform(x + a, y)
    _, y1 = to_merc.transform(x, y + e)
    return math.sqrt(abs(x1 - x0) * abs(y1 - y0)) / view.merc_scale


# region reproject-to-view
def reproject_to_view(
    src: np.ndarray,
    src_transform,
    src_crs,
    view: View,
    resampling: str = "auto",
    src_nodata=None,
) -> np.ndarray:
    """Resample a 2-D (rows, cols) or 3-D (bands, rows, cols) array onto `view`.

    Returns float32 with NaN where there is no data. `resampling` is a
    rasterio Resampling name, or "auto": nearest when the source is coarser
    than the output pixels, average when finer. Use "nearest" or "mode" for
    categorical data.
    """
    src = np.asarray(src)
    squeeze = src.ndim == 2
    if squeeze:
        src = src[None]
    src = src.astype("float32")
    if src_nodata is not None and not (isinstance(src_nodata, float) and math.isnan(src_nodata)):
        src = np.where(src == src_nodata, np.nan, src)
    if resampling == "auto":
        coarse = native_pixel_size_m(src_transform, src_crs, view) > view.pixel_size_m
        resampling = "nearest" if coarse else "average"
    dst = np.full((src.shape[0], *view.shape), np.nan, dtype="float32")
    reproject(
        source=src,
        destination=dst,
        src_transform=src_transform,
        src_crs=RioCRS.from_user_input(src_crs),
        src_nodata=np.nan,
        dst_transform=view.transform,
        dst_crs=CRS,
        dst_nodata=np.nan,
        resampling=Resampling[resampling],
    )
    return dst[0] if squeeze else dst
# endregion reproject-to-view


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------


def percentiles(data: np.ndarray, lo: float = 2, hi: float = 98) -> tuple[float, float]:
    """Robust (nan-aware) value range for stretching."""
    v = np.asarray(data)[np.isfinite(data)]
    return float(np.percentile(v, lo)), float(np.percentile(v, hi))


def stretch(data: np.ndarray, vmin: float, vmax: float, gamma: float = 1.0) -> np.ndarray:
    """Linear stretch to 0-1 (NaN preserved), with optional gamma."""
    out = np.clip((np.asarray(data, dtype="float32") - vmin) / (vmax - vmin), 0, 1)
    return out ** (1 / gamma) if gamma != 1 else out


def to_rgba(rgb: np.ndarray) -> np.ndarray:
    """(3, h, w) or (h, w, 3) floats in 0-1 (NaN = nodata) to RGBA uint8."""
    rgb = np.asarray(rgb, dtype="float32")
    if rgb.shape[0] == 3 and rgb.ndim == 3 and rgb.shape[-1] != 3:
        rgb = np.moveaxis(rgb, 0, -1)
    valid = np.all(np.isfinite(rgb), axis=-1)
    out = np.zeros((*rgb.shape[:2], 4), dtype="uint8")
    out[..., :3] = np.round(np.nan_to_num(np.clip(rgb, 0, 1)) * 255)
    out[..., 3] = np.where(valid, 255, 0)
    return out


def colorize(data: np.ndarray, cmap, vmin=None, vmax=None, norm=None) -> np.ndarray:
    """Apply a colormap to a 2-D array; NaN becomes transparent. Returns RGBA uint8."""
    cmap = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap
    norm = norm or mcolors.Normalize(vmin=vmin, vmax=vmax)
    data = np.ma.masked_invalid(data)
    out = cmap(norm(data), bytes=True)
    out[..., 3] = np.where(np.ma.getmaskarray(data), 0, out[..., 3])
    return out


# region hillshade-and-blend
def hillshade(dem: np.ndarray, dx: float, dy: float | None = None, azimuth=315.0, altitude=45.0, z_factor=1.0):
    """Hillshade (0-1) of a north-up DEM with pixel spacing dx, dy in the DEM's z units.

    `azimuth` is the sun's compass bearing (degrees clockwise from north).
    """
    dy = dx if dy is None else dy
    # gy is d/drow, i.e. toward the south; gx is d/dcol, toward the east.
    gy, gx = np.gradient(np.asarray(dem, dtype="float32") * z_factor, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    # Check the angle convention: compass (0 = north, clockwise) vs. math
    # (0 = east, counterclockwise). Both angles here are compass; mixing the two
    # mirrors the light across the NE-SW line (azimuth 315 would light from 135).
    aspect_compass = np.arctan2(-gx, gy)  # downslope direction: (east, north) = (-gx, gy)
    az_compass, alt = np.radians(azimuth), np.radians(altitude)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az_compass - aspect_compass)
    return np.clip(hs, 0, 1)


def blend_hillshade(rgba: np.ndarray, hs: np.ndarray, strength: float = 0.6) -> np.ndarray:
    """Multiply-blend a hillshade (0-1, NaN ok) into an RGBA uint8 image."""
    shade = 1 - strength + strength * np.nan_to_num(hs, nan=1.0)
    out = rgba.copy()
    out[..., :3] = np.clip(rgba[..., :3] * shade[..., None], 0, 255).astype("uint8")
    return out
# endregion hillshade-and-blend


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def save_png(img: np.ndarray, path: Path) -> Path:
    """Write an (h, w, 3|4) uint8 image exactly, pixel for pixel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(img)).save(path, optimize=True)
    return path


def map_figure(view: View, image: np.ndarray | None = None, facecolor=NODATA_FACE):
    """A figure whose single axes covers exactly the view, one figure pixel per view pixel.

    Axes data coordinates are EPSG:3857 x/y, so vector overlays can be drawn
    with `view.to_xy(lon, lat)`.
    """
    fig = plt.figure(figsize=(view.width_px / DPI, view.height_px / DPI), dpi=DPI, facecolor=facecolor)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_facecolor(facecolor)
    ax.set_xlim(view.extent[0], view.extent[1])
    ax.set_ylim(view.extent[2], view.extent[3])
    ax.set_axis_off()
    if image is not None:
        ax.imshow(image, extent=view.extent, origin="upper", interpolation="none", zorder=0)
        ax.set_xlim(view.extent[0], view.extent[1])
        ax.set_ylim(view.extent[2], view.extent[3])
    return fig, ax


_HALO = [pe.withStroke(linewidth=3, foreground="black")]
_BOX = dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="none", alpha=0.85)


def _nice_length(max_m: float) -> float:
    exp = 10 ** math.floor(math.log10(max_m))
    return max(m * exp for m in (1, 2, 5) if m * exp <= max_m)


def add_scalebar(ax, view: View):
    length_m = _nice_length(view.width_m / 5)
    xmin, ymin, xmax, ymax = view.bounds
    w, h = xmax - xmin, ymax - ymin
    x0, y0 = xmin + 0.02 * w, ymin + 0.045 * h
    lm = length_m * view.merc_scale
    ax.add_patch(
        Rectangle((x0 - 0.008 * w, y0 - 0.02 * h), lm + 0.016 * w, 0.075 * h, fc="white", ec="none", alpha=0.85, zorder=20)
    )
    ax.add_patch(Rectangle((x0, y0), lm, 0.008 * h, fc="black", ec="black", zorder=21))
    ax.add_patch(Rectangle((x0, y0), lm / 2, 0.008 * h, fc="white", ec="black", lw=0.8, zorder=22))
    label = f"{length_m / 1000:g} km" if length_m >= 1000 else f"{length_m:g} m"
    ax.text(x0 + lm / 2, y0 + 0.016 * h, label, ha="center", va="bottom", fontsize=13, zorder=22)


# Landmarks whose label goes to the left of the marker, to avoid overlaps.
_LABEL_LEFT = {"Sterling Memorial Library"}


def add_landmarks(ax, view: View, color="white"):
    xmin, ymin, xmax, ymax = view.bounds
    for lm in load_landmarks():
        x, y = view.to_xy(lm["lon"], lm["lat"])
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            continue
        ax.plot(x, y, "o", ms=10, mfc=color, mec="black", mew=1.5, zorder=30)
        ax.annotate(
            lm["name"],
            (x, y),
            xytext=(-10, 8) if lm["name"] in _LABEL_LEFT else (10, 8),
            textcoords="offset points",
            ha="right" if lm["name"] in _LABEL_LEFT else "left",
            fontsize=15,
            fontweight="bold",
            color=color,
            path_effects=_HALO,
            zorder=31,
        )


def add_colorbar(ax, cmap, norm, label: str, extend="neither", ticks=None):
    """Horizontal colorbar in a white box at the lower right of the map."""
    ax.add_patch(
        Rectangle((0.69, 0.035), 0.295, 0.135, transform=ax.transAxes, fc="white", ec="none", alpha=0.85, zorder=20)
    )
    cax = ax.inset_axes((0.705, 0.09, 0.265, 0.025), zorder=21)
    cmap = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal", extend=extend)
    if ticks is not None:
        cb.set_ticks(ticks)
    cb.ax.tick_params(labelsize=12)
    cb.set_label(label, fontsize=14, labelpad=6)
    cb.ax.xaxis.set_label_position("top")
    return cb


def add_legend(ax, entries: list[tuple], title: str | None = None, ncol: int = 1):
    """Categorical legend from (color, label) pairs at the lower right."""
    handles = [Patch(facecolor=c, edgecolor="black", linewidth=0.5, label=l) for c, l in entries]
    leg = ax.legend(
        handles=handles,
        title=title,
        loc="lower right",
        bbox_to_anchor=(0.985, 0.035),
        fontsize=12,
        title_fontsize=13,
        framealpha=0.85,
        edgecolor="none",
        ncol=ncol,
    )
    leg.set_zorder(25)
    return leg


def add_labels(
    ax,
    view: View,
    title: str,
    subtitle: str | None = None,
    colorbar: dict | None = None,
    legend: dict | None = None,
    source: str | None = None,
    landmarks: bool = True,
    landmark_color: str = "white",
):
    """Title block, scale bar, landmarks, colorbar or legend, and source line.

    colorbar: dict(cmap=..., norm=Normalize(...), label=..., [extend, ticks])
    legend:   dict(entries=[(color, label), ...], [title, ncol])
    """
    lines = [subtitle] if subtitle else []
    lines.append(view.title)
    ax.text(
        0.015,
        0.975,
        title,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=24,
        fontweight="bold",
        bbox=_BOX,
        zorder=40,
    )
    ax.text(0.015, 0.905, "\n".join(lines), transform=ax.transAxes, ha="left", va="top", fontsize=16, bbox=_BOX, zorder=40)
    add_scalebar(ax, view)
    if landmarks:
        add_landmarks(ax, view, landmark_color)
    if colorbar:
        add_colorbar(ax, **colorbar)
    if legend:
        add_legend(ax, **legend)
    if source:
        ax.text(
            0.985,
            0.008,
            source,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=10,
            color="black",
            bbox=dict(boxstyle="square,pad=0.25", facecolor="white", edgecolor="none", alpha=0.7),
            zorder=40,
        )


def save_figure(fig, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


# region save-figures
def save_figures(img: np.ndarray, view: View, dataset: str, product: str, **label_kwargs) -> tuple[Path, Path]:
    """Write figures/<dataset>/<view>_<product>.png (data only) and ..._labeled.png.

    `label_kwargs` go to `add_labels` (title is required).
    """
    plain, labeled = config.figure_paths(dataset, view.name, product)
    assert img.shape[:2] == view.shape, f"image {img.shape[:2]} != view {view.shape}"
    save_png(img, plain)
    fig, ax = map_figure(view, img)
    add_labels(ax, view, **label_kwargs)
    save_figure(fig, labeled)
    print(f"  wrote {plain.relative_to(config.REPO)} and {labeled.name}")
    return plain, labeled
# endregion save-figures
