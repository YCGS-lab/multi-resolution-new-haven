# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "h5py", "pyresample"]
# ///
"""VIIRS 375 m land surface temperature (NOAA-21 VJ221IMG_NRT), 2026-10-02.

Product `lst`: LST from the I5 single-channel algorithm, in deg C.

The data are an L2 swath with per-pixel Latitude/Longitude in the file. The
swath is resampled to each view grid by nearest neighbour (pyresample
kd-tree) with a radius of influence slightly larger than half the pixel
diagonal, so every output pixel takes the value of the swath pixel whose
center is closest: native ~375 m footprints show up as blocks (Voronoi cells
of the pixel centers), with no interpolation across pixels. Masked pixels
(cloud, water) stay in the tree as NaN, so they keep their footprints too
instead of being filled by neighbours.

Quality: mandatory QA (QC bits 1-0) 10 = cloud and 11 = not produced (water
etc.) have no LST. 00 = "best quality" and 01 = "nominal quality" (near
cloud, low emissivity or low transmissivity; usable with caution per the
VNP21 user guide) are both shown, because in this scene the best-quality
pixels miss downtown and the coast entirely (they are within the cloud-edge
buffer). In the labeled figures the 01 pixels are hatched, cloud is gray and
not-produced (water) pixels are light blue; the data-only PNGs show LST
only (both QA classes, transparent elsewhere).
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h5py
import numpy as np
from matplotlib.colors import Normalize
from pyresample import geometry, kd_tree

from common import config, render, views
from common.views import CRS, VIEWS

DATASET = "viirs-lst"
FILE_GLOB = "VJ221IMG_NRT.A2026275.1748.002.*.nc"
GROUP = "VIIRS_I5_LST"
PAD_M = 1000.0  # > 2 native pixels
LINES_PER_SCAN = 32  # VIIRS I-bands
CMAP = "inferno"  # same as the Landsat LST figures
SOURCE = "NASA LANCE VIIRS LST VJ221IMG_NRT v002 (NOAA-21), LAADS/MODAPS"


def read_subset(path: Path):
    """Swath rows/cols covering the views: LST (deg C, NaN = cloud/water), QA, lat, lon, view angle."""
    w, s, e, n = views.all_bounds_lonlat(PAD_M)
    with h5py.File(path) as f:
        g = f[GROUP]
        lat = g["Geolocation Fields/Latitude"][:]
        lon = g["Geolocation Fields/Longitude"][:]
        inside = (lat >= s) & (lat <= n) & (lon >= w) & (lon <= e)
        rows, cols = np.nonzero(inside)
        # One extra line/pixel on each side, so edge pixels have their neighbours.
        r0, r1 = max(rows.min() - 1, 0), min(rows.max() + 2, lat.shape[0])
        c0, c1 = max(cols.min() - 1, 0), min(cols.max() + 2, lat.shape[1])
        sl = (slice(r0, r1), slice(c0, c1))

        def read(name):
            ds = g[f"Data Fields/{name}"]
            raw = ds[sl]
            scale = float(ds.attrs.get("scale_factor", [1.0])[0])
            offset = float(ds.attrs.get("add_offset", [0.0])[0])
            return raw, raw * scale + offset

        lst_raw, lst_k = read("LST")
        qc, _ = read("QC")
        _, view_angle = read("View_angle")
        attrs = {k: f.attrs[k] for k in ("time_coverage_start", "time_coverage_end")}
        attrs["n_lines"] = lat.shape[0]
    qa = (qc & 0b11).astype("float32")
    keep = (lst_raw > 0) & (qa <= 1)
    lst = np.where(keep, lst_k - 273.15, np.nan).astype("float32")
    qa = np.where(keep | (qa >= 2), qa, 3).astype("float32")  # 0 best, 1 nominal, 2 cloud, 3 not produced
    lat, lon = lat[sl], lon[sl]
    sub = inside[sl]
    print(f"  swath rows {r0}-{r1 - 1}, cols {c0}-{c1 - 1}; view angle {view_angle[sub].min():.1f}-{view_angle[sub].max():.1f} deg")
    counts = {q: int(((qc[sub] & 3) == q).sum()) for q in range(4)}
    print(f"  mandatory QA counts in views (00 best, 01 nominal, 10 cloud, 11 not produced): {counts}")
    return lst, qa, lat, lon, view_angle[sub], (r0 + r1) / 2, attrs


def pixel_spacing_m(lat, lon) -> tuple[float, float]:
    """Median ground distance between neighbouring swath pixel centers (along-scan, along-track)."""
    k = np.cos(np.radians(np.nanmean(lat))) * 111320.0
    d_scan = np.hypot(np.diff(lon, axis=1) * k, np.diff(lat, axis=1) * 111320.0)
    d_track = np.hypot(np.diff(lon, axis=0) * k, np.diff(lat, axis=0) * 111320.0)
    return float(np.median(d_scan)), float(np.median(d_track))


def view_area(view) -> geometry.AreaDefinition:
    return geometry.AreaDefinition(view.name, view.title, view.name, CRS, view.width_px, view.height_px, view.bounds)


def overpass_time(attrs, row: float) -> datetime:
    """Approximate time the view was scanned: granule start + scan index * scan period."""
    start = datetime.fromisoformat(attrs["time_coverage_start"].decode().replace("Z", "+00:00"))
    end = datetime.fromisoformat(attrs["time_coverage_end"].decode().replace("Z", "+00:00"))
    n_scans = attrs["n_lines"] / LINES_PER_SCAN
    return start + (end - start) * (row / LINES_PER_SCAN) / n_scans


MASK_COLORS = {2: (175, 175, 175), 3: (188, 215, 234)}  # cloud: gray; not produced (water etc.): light blue


def mask_rgba(qa: np.ndarray) -> np.ndarray:
    """Opaque colors for the pixels without LST (QA 10 cloud, 11 not produced)."""
    out = np.zeros((*qa.shape, 4), dtype="uint8")
    for q, rgb in MASK_COLORS.items():
        out[qa == q] = (*rgb, 255)
    return out


def hatch_rgba(mask: np.ndarray, period: int = 14, width: int = 3) -> np.ndarray:
    """Semi-transparent white diagonal stripes where mask is True (RGBA uint8)."""
    i, j = np.indices(mask.shape)
    stripes = mask & (((i + j) % period) < width)
    out = np.zeros((*mask.shape, 4), dtype="uint8")
    out[stripes] = (255, 255, 255, 170)
    return out


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    path = paths[-1]
    print(path.name)
    lst, qa, lat, lon, vza, row, attrs = read_subset(path)

    d_scan, d_track = pixel_spacing_m(lat, lon)
    radius = 0.6 * np.hypot(d_scan, d_track)  # > half the pixel diagonal: no gaps between pixels
    print(f"  pixel spacing {d_scan:.0f} m along scan x {d_track:.0f} m along track; radius of influence {radius:.0f} m")
    swath = geometry.SwathDefinition(lons=lon, lats=lat)

    t = overpass_time(attrs, row).replace(second=0, microsecond=0)
    t_local = t.astimezone(ZoneInfo("America/New_York"))
    when = f"{t:%Y-%m-%d %H:%M} UTC ({t_local:%H:%M} {t_local.tzname()})"
    print(f"  overpass ~{when}")

    grids = {}
    for view in VIEWS.values():
        area = view_area(view)
        info = kd_tree.get_neighbour_info(swath, area, radius, neighbours=1, epsilon=0)
        lst_g, qa_g = (
            kd_tree.get_sample_from_neighbour_info("nn", area.shape, a, *info, fill_value=np.nan).astype("float32")
            for a in (lst, qa)
        )
        grids[view.name] = (lst_g, qa_g)
    # One color range for both views, from the greater view (2-98th percentile, rounded).
    lo, hi = render.percentiles(grids["greater"][0], 2, 98)
    norm = Normalize(np.floor(lo), np.ceil(hi))
    print(f"  color range {norm.vmin:g} to {norm.vmax:g} deg C")

    for view in VIEWS.values():
        print(view.title)
        grid, qa_g = grids[view.name]
        valid = np.isfinite(grid)
        print(
            f"  LST in view {np.nanmin(grid):.1f} to {np.nanmax(grid):.1f} deg C; "
            f"{valid.mean():.0%} valid ({(qa_g == 0).mean():.0%} best, {(qa_g == 1).mean():.0%} nominal QC), "
            f"{(qa_g == 2).mean():.0%} cloud, {(qa_g == 3).mean():.0%} not produced"
        )
        img = render.colorize(grid, CMAP, norm=norm)
        # Same as render.save_figures, plus hatching of nominal-quality pixels in the labeled figure.
        plain, labeled = config.figure_paths(DATASET, view.name, "lst")
        render.save_png(img, plain)
        fig, ax = render.map_figure(view, img)
        ax.imshow(mask_rgba(qa_g), extent=view.extent, origin="upper", interpolation="none", zorder=1)
        ax.imshow(hatch_rgba(qa_g == 1), extent=view.extent, origin="upper", interpolation="none", zorder=1)
        render.add_labels(
            ax, view,
            title="VIIRS land surface temperature (NOAA-21)",
            subtitle=(
                f"{when}, view angle {vza.min():.0f}-{vza.max():.0f}°; 375 m I5 pixels (nearest neighbour)\n"
                "Hatched: nominal-quality QC (near cloud); gray: cloud; light blue: water / not retrieved"
            ),
            colorbar=dict(cmap=CMAP, norm=norm, label="Land surface temperature (°C)", extend="both"),
            source=SOURCE,
            landmark_color="cyan",
        )  # fmt: skip
        render.save_figure(fig, labeled)
        print(f"  wrote {plain.relative_to(config.REPO)} and {labeled.name}")


if __name__ == "__main__":
    main()
