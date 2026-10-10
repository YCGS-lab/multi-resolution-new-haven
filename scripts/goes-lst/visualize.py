# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "netcdf4"]
# ///
"""GOES-19 ABI land surface temperature (ABI-L2-LSTC, CONUS, 2 km), 2026-06-03 18:01 UTC.

Product `lst`: LST in deg C.

Georeferencing: the L2 product is on the ABI fixed grid, a geostationary
projection defined by the `goes_imager_projection` variable (+proj=geos with
the perspective point height h, lon_0 = -75, sweep = x, GRS80 ellipsoid).
The x/y coordinates are scan angles (rad) of the pixel *centers*; times h
they are projection meters. The affine transform is built from the cell
edges (first center minus half a pixel), which is checked against the
`x_image_bounds` / `y_image_bounds` (image edges) in the file. Data are
resampled onto each view with nearest neighbour, so the native pixels show
up as blocks: 56 urad = 2.0 km at nadir, but at New Haven (41.3 N, 1.9 deg
east of the sub-satellite meridian, view zenith ~48 deg) the footprint is
stretched north-south (~2.0 km E-W x ~3.0 km N-S; printed by this script).

Quality: DQF 0 (high) and 1 (medium) are shown, medium hatched in the
labeled figure; DQF 2 (low quality) and 3 (no retrieval) have no LST. In the
labeled figures no-retrieval pixels flagged (probably) cloudy in PQI are
gray, other no-retrieval pixels (water) light blue, low quality dark gray.
At this hour every land pixel over the views is DQF 0 and cloud-free.

Color scale: styles.LST_RANGE is shared with scripts/viirs-lst/visualize.py (VIIRS
VNP21 750 m, 9 minutes earlier), so the two are directly comparable.
"""

import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netCDF4
import numpy as np
from matplotlib.colors import Normalize
from pyproj import CRS as ProjCRS
from pyproj import Geod, Transformer
from rasterio.transform import Affine

from common import config, render, styles
from common.views import VIEWS

DATASET = "goes-lst"
FILE_GLOB = "OR_ABI-L2-LSTC-M6_G19_s20261541801*.nc"
PAD_M = 8000.0  # > 2 native pixels (~3 km N-S here)
CMAP = styles.LST_CMAP
LST_RANGE = styles.LST_RANGE
SOURCE = "NOAA GOES-19 ABI L2 Land Surface Temperature (ABI-L2-LSTC), NOAA Open Data on AWS"


# region abi-fixed-grid
def geos_crs(d: netCDF4.Dataset) -> ProjCRS:
    p = d["goes_imager_projection"]
    return ProjCRS.from_proj4(
        f"+proj=geos +h={p.perspective_point_height} +lon_0={p.longitude_of_projection_origin} "
        f"+sweep={p.sweep_angle_axis} +a={p.semi_major_axis} +b={p.semi_minor_axis} +units=m +no_defs"
    )


def coords_m(d: netCDF4.Dataset, name: str) -> np.ndarray:
    """Pixel-center coordinates in projection meters (scan angle x h), in float64."""
    v = d[name]
    v.set_auto_maskandscale(False)
    raw = v[:].astype("float64")
    return (raw * float(v.scale_factor) + float(v.add_offset)) * float(d["goes_imager_projection"].perspective_point_height)


def grid_transform(d: netCDF4.Dataset):
    """Affine transform of the cell edges, verified against the image bounds in the file."""
    h = float(d["goes_imager_projection"].perspective_point_height)
    x, y = coords_m(d, "x"), coords_m(d, "y")
    dx, dy = (x[-1] - x[0]) / (len(x) - 1), (y[-1] - y[0]) / (len(y) - 1)  # dy < 0 (north up)
    transform = Affine(dx, 0, x[0] - dx / 2, 0, dy, y[0] - dy / 2)
    xb, yb = d["x_image_bounds"][:] * h, d["y_image_bounds"][:] * h
    edges = (x[0] - dx / 2, x[-1] + dx / 2, y[0] - dy / 2, y[-1] + dy / 2)
    err = np.max(np.abs(np.array(edges) - np.array([xb[0], xb[1], yb[0], yb[1]])))
    print(f"  pixel {dx:.1f} x {-dy:.1f} m (projection); edges vs x/y_image_bounds: max diff {err:.1f} m")
    assert err < 0.05 * abs(dx), "half-pixel convention mismatch"
    return transform, x, y
# endregion abi-fixed-grid


# region footprint-and-view-zenith
def ground_footprint_m(crs, transform, lon, lat) -> tuple[float, float, float]:
    """Ground size (E-W, N-S) of one pixel at lon/lat, and the satellite view zenith angle."""
    to_geos = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    geod = Geod(ellps="GRS80")
    x, y = to_geos.transform(lon, lat)
    a, e = transform.a, transform.e
    lon_x, lat_x = to_ll.transform(x + a, y)
    lon_y, lat_y = to_ll.transform(x, y + e)
    ew = geod.inv(lon, lat, lon_x, lat_x)[2]
    ns = geod.inv(lon, lat, lon_y, lat_y)[2]
    # View zenith angle: satellite position vs. local vertical (spherical approximation is fine here).
    proj = {k: v for k, v in (t.lstrip("+").split("=") for t in crs.srs.split() if "=" in t)}
    r_e, r_s = 6371.0, 6371.0 + float(proj["h"]) / 1000
    gamma = math.acos(math.cos(math.radians(lat)) * math.cos(math.radians(lon - float(proj["lon_0"]))))
    vza = math.degrees(math.atan2(r_s * math.sin(gamma), r_s * math.cos(gamma) - r_e))
    return ew, ns, vza
# endregion footprint-and-view-zenith


MASK_COLORS = {2: (110, 110, 110), 3: (175, 175, 175), 4: (188, 215, 234)}  # low quality, cloud, water/other


def mask_rgba(cls: np.ndarray) -> np.ndarray:
    out = np.zeros((*cls.shape, 4), dtype="uint8")
    for q, rgb in MASK_COLORS.items():
        out[cls == q] = (*rgb, 255)
    return out


def hatch_rgba(mask: np.ndarray, period: int = 14, width: int = 3) -> np.ndarray:
    """Semi-transparent white diagonal stripes where mask is True (RGBA uint8)."""
    i, j = np.indices(mask.shape)
    out = np.zeros((*mask.shape, 4), dtype="uint8")
    out[mask & (((i + j) % period) < width)] = (255, 255, 255, 170)
    return out


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    path = paths[-1]
    print(path.name)
    with netCDF4.Dataset(path) as d:
        crs = geos_crs(d)
        transform, x, y = grid_transform(d)
        # Window covering every view (the greater view contains the central one), padded.
        xmin, ymin, xmax, ymax = VIEWS["greater"].bounds_in(crs, PAD_M)
        cols = np.nonzero((x >= xmin) & (x <= xmax))[0]
        rows = np.nonzero((y >= ymin) & (y <= ymax))[0]
        sl = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
        lst_k = d["LST"][sl].astype("float64").filled(np.nan)  # auto-scaled to K, fill masked
        dqf = d["DQF"][sl].filled(3)
        d["PQI"].set_auto_maskandscale(False)
        pqi = d["PQI"][sl]
        t0, t1 = parse_time(d.time_coverage_start), parse_time(d.time_coverage_end)
        resolution, platform = d.spatial_resolution, d.platform_ID
    win_transform = transform * Affine.translation(cols[0], rows[0])
    print(f"  window rows {rows[0]}-{rows[-1]}, cols {cols[0]}-{cols[-1]} ({lst_k.shape[0]}x{lst_k.shape[1]} pixels)")

    cloudy = ((pqi >> 2) & 3) >= 2  # probably cloudy / cloudy
    show = (dqf <= 1) & np.isfinite(lst_k)
    lst = np.where(show, lst_k - 273.15, np.nan)
    # Classes: 0 high, 1 medium, 2 low quality, 3 no retrieval + cloud, 4 no retrieval otherwise (water).
    cls = np.where(show, dqf, np.where(dqf == 2, 2, np.where(cloudy, 3, 4))).astype("float32")

    v = VIEWS["greater"]
    ew, ns, vza = ground_footprint_m(crs, transform, v.lon, v.lat)
    print(f"  footprint at New Haven ~{ew / 1000:.2f} km E-W x {ns / 1000:.2f} km N-S; view zenith {vza:.0f} deg")
    t_local = t0.astimezone(ZoneInfo("America/New_York"))
    when = f"{t0:%Y-%m-%d %H:%M}-{t1:%H:%M} UTC ({t_local:%H:%M} {t_local.tzname()})"
    print(f"  scan {when}; {platform}, {resolution}")

    norm = Normalize(*LST_RANGE)
    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(lst, win_transform, crs, view, resampling="nearest")
        cls_g = render.reproject_to_view(cls, win_transform, crs, view, resampling="nearest")
        valid = np.isfinite(grid)
        print(
            f"  LST in view {np.nanmin(grid):.1f} to {np.nanmax(grid):.1f} deg C; {valid.mean():.0%} valid "
            f"({(cls_g == 0).mean():.0%} high, {(cls_g == 1).mean():.0%} medium DQF), "
            f"{(cls_g == 2).mean():.0%} low quality, {(cls_g == 3).mean():.0%} cloud, {(cls_g == 4).mean():.0%} water/other"
        )
        img = render.colorize(grid, CMAP, norm=norm)
        plain, labeled = config.figure_paths(DATASET, view.name, "lst")
        render.save_png(img, plain)
        fig, ax = render.map_figure(view, img)
        ax.imshow(mask_rgba(cls_g), extent=view.extent, origin="upper", interpolation="none", zorder=1)
        ax.imshow(hatch_rgba(cls_g == 1), extent=view.extent, origin="upper", interpolation="none", zorder=1)
        notes = [
            label
            for present, label in (
                ((cls_g == 1).any(), "hatched: medium quality"),
                ((cls_g == 2).any(), "dark gray: low quality (masked)"),
                ((cls_g == 3).any(), "gray: cloud"),
                ((cls_g == 4).any(), "light blue: water / not retrieved"),
            )
            if present
        ]
        render.add_labels(
            ax, view,
            title=f"GOES-{platform[1:]} ABI land surface temperature (2 km)",
            subtitle=(
                f"Scan {when}, view zenith {vza:.0f}°; ABI-L2-LSTC (CONUS), 2 km at nadir, "
                f"~{ew / 1000:.1f} × {ns / 1000:.1f} km here (nearest neighbour)"
                + ("\n" + "; ".join(notes)[:1].upper() + "; ".join(notes)[1:] if notes else "")
            ),
            colorbar=dict(cmap=CMAP, norm=norm, label="Land surface temperature (°C)", extend="both"),
            source=SOURCE,
            landmark_color="cyan",
        )  # fmt: skip
        render.save_figure(fig, labeled)
        print(f"  wrote {plain.relative_to(config.REPO)} and {labeled.name}")


if __name__ == "__main__":
    main()
