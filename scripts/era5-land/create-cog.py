# /// script
# requires-python = ">=3.11"
# dependencies = ["xarray", "netcdf4", "numpy", "astral", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ERA5-Land 2 m air temperature at the four times of day (see timing.py) as
one COG for the website: bands t2m_night, t2m_sunrise, t2m_midday,
t2m_sunset (deg C), nearest-neighbor on a ~30 m Web Mercator grid so the
0.1 deg cells keep their footprints. One color range for all four times
(data range over the extent, rounded out to whole degrees).
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

import timing
from common import config, web
from visualize import CMAP, DATASET, LABELS, SOURCE, grid_transform

NATIVE_M = 0.1 * 111320 * math.cos(math.radians(web.EXTENT_VIEW.lat))  # E-W size of a 0.1 deg cell


def main():
    path = config.data_dir(DATASET) / f"era5-land_t2m_{timing.DATE:%Y%m%d}.nc"
    with xr.open_dataset(path) as ds:
        ds = ds.sortby("latitude", ascending=False).load()
    transform = grid_transform(ds.latitude.values, ds.longitude.values)
    times = timing.product_times()
    grid = web.fine_grid(NATIVE_M)
    fields = []
    for product, (_, hour) in times.items():
        t_utc = np.datetime64(hour.astimezone(dt.UTC).replace(tzinfo=None), "ns")
        t2m = ds.t2m.sel(valid_time=t_utc).values.astype("float32") - 273.15
        fields.append(web.reproject(t2m, transform, "EPSG:4326", grid))
    data = np.stack(fields)
    vals = data[np.isfinite(data)]
    vmin, vmax = math.floor(vals.min()), math.ceil(vals.max())
    print(f"t2m over the extent {vals.min():.2f} to {vals.max():.2f} degC; color range {vmin} to {vmax}")
    sources = {"t2m": web.write_cog(DATASET, data, grid, list(times), max_z_error=0.005)}

    norm = Normalize(vmin, vmax)
    products = {}
    for product, (event, hour) in times.items():
        utc = hour.astimezone(dt.UTC)
        products[product] = web.product(
            title=f"ERA5-Land 2 m air temperature, {LABELS[product]}",
            subtitle=(
                f"{hour:%-d %B %Y}, {hour:%H:%M} EDT ({utc:%H:%M} UTC{'' if utc.date() == hour.date() else f' {utc:%-d %b}'}); "
                f"{LABELS[product]} {event:%H:%M} EDT\n"
                "Land only (sea cells transparent)"
            ),
            native="0.1° grid (~8 km E-W × 11 km N-S here; native model ~9 km)",
            source=SOURCE,
            layers=[web.layer("t2m", web.colormap(CMAP, norm, "2 m air temperature (°C)", band=product))],
        )
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
