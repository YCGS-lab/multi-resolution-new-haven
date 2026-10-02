# /// script
# requires-python = ">=3.11"
# dependencies = ["xarray", "netcdf4", "numpy", "astral", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ERA5-Land hourly 2 m air temperature over New Haven on one clear summer
day, at four times of day (see timing.py), on both views.

ERA5-Land is served by the CDS on a regular 0.1 deg lat/lon grid whose values
are at cell centers on multiples of 0.1 deg, so a cell centered on (lon, lat)
spans lon +/- 0.05, lat +/- 0.05. ERA5-Land is land-only: sea cells are NaN
and shown transparent. One color range is shared by all four times and both
views so the diurnal cycle is comparable.

Figures (per view): t2m_night, t2m_sunrise, t2m_midday, t2m_sunset.
"""

import datetime as dt
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import xarray as xr
from matplotlib.colors import Normalize
from rasterio.transform import Affine, xy

import timing
from common import config, render
from common.views import VIEWS

DATASET = "era5-land"
CMAP = "RdYlBu_r"
SOURCE = "ERA5-Land hourly reanalysis (Copernicus Climate Change Service / ECMWF), cds.climate.copernicus.eu"
LABELS = {"t2m_night": "middle of the night", "t2m_sunrise": "sunrise", "t2m_midday": "solar noon", "t2m_sunset": "sunset"}


def grid_transform(lat: np.ndarray, lon: np.ndarray) -> Affine:
    """Affine transform (pixel edges) for a regular grid given its cell-center coordinates.

    `lat` must be descending (north-up). Checks that the grid is regular and
    that centers sit on multiples of the spacing, then verifies the transform
    maps each pixel center back onto its coordinate.
    """
    dx, dy = float(np.diff(lon).mean()), float(np.diff(lat).mean())
    assert dy < 0, "latitude must be descending"
    assert np.allclose(np.diff(lon), dx, atol=1e-6) and np.allclose(np.diff(lat), dy, atol=1e-6), "grid is not regular"
    assert np.allclose(np.round(lon / dx) * dx, lon, atol=1e-4) and np.allclose(np.round(lat / dy) * dy, lat, atol=1e-4)
    transform = Affine(dx, 0, lon[0] - dx / 2, 0, dy, lat[0] - dy / 2)
    rows, cols = np.arange(len(lat)), np.arange(len(lon))
    xs, _ = xy(transform, np.zeros_like(cols), cols, offset="center")
    _, ys = xy(transform, rows, np.zeros_like(rows), offset="center")
    assert np.allclose(xs, lon, atol=1e-6) and np.allclose(ys, lat, atol=1e-6), "transform does not match cell centers"
    return transform


def main():
    path = config.data_dir(DATASET) / f"era5-land_t2m_{timing.DATE:%Y%m%d}.nc"
    with xr.open_dataset(path) as ds:
        ds = ds.sortby("latitude", ascending=False).load()
    lat, lon = ds.latitude.values, ds.longitude.values
    transform = grid_transform(lat, lon)
    print(f"grid {len(lat)}x{len(lon)}, lat {lat[0]:.2f}..{lat[-1]:.2f}, lon {lon[0]:.2f}..{lon[-1]:.2f}; {transform!r}")

    times = timing.product_times()
    fields = {}
    for product, (_, hour) in times.items():
        t_utc = np.datetime64(hour.astimezone(dt.UTC).replace(tzinfo=None), "ns")
        fields[product] = ds.t2m.sel(valid_time=t_utc).values.astype("float32") - 273.15

    grids = {
        (v.name, p): render.reproject_to_view(f, transform, "EPSG:4326", v, resampling="nearest")
        for v in VIEWS.values()
        for p, f in fields.items()
    }
    # One color range for all times and views: data range in the greater view, rounded out to whole degC.
    allvals = np.concatenate([g[np.isfinite(g)] for g in grids.values()])
    vmin, vmax = math.floor(allvals.min()), math.ceil(allvals.max())
    norm = Normalize(vmin, vmax)
    print(f"t2m in views {allvals.min():.2f} to {allvals.max():.2f} degC; color range {vmin} to {vmax} degC")

    for view in VIEWS.values():
        print(view.title)
        for product, (event, hour) in times.items():
            grid = grids[(view.name, product)]
            vals = grid[np.isfinite(grid)]
            print(f"  {product}: {vals.min():.2f} to {vals.max():.2f} degC, {np.isnan(grid).mean():.0%} nodata")
            utc = hour.astimezone(dt.UTC)
            subtitle = (
                f"{hour:%-d %B %Y}, {hour:%H:%M} EDT ({utc:%H:%M} UTC{'' if utc.date() == hour.date() else f' {utc:%-d %b}'}); "
                f"{LABELS[product]} {event:%H:%M} EDT\n"
                "0.1° grid (~8 km E-W x 11 km N-S here; native model ~9 km); land only (sea cells transparent)"
            )
            render.save_figures(
                render.colorize(grid, CMAP, norm=norm), view, DATASET, product,
                title=f"ERA5-Land 2 m air temperature, {LABELS[product]}",
                subtitle=subtitle,
                colorbar=dict(cmap=CMAP, norm=norm, label="2 m air temperature (°C)"),
                source=SOURCE,
            )  # fmt: skip


if __name__ == "__main__":
    main()
