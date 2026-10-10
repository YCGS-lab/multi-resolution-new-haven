# /// script
# requires-python = ">=3.11"
# dependencies = ["netcdf4", "numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""GOES-19 ABI land surface temperature (ABI-L2-LSTC, 2 km) as a COG for the
website: band lst (deg C; DQF 0 and 1 only, as in visualize.py), resampled
from the ABI fixed grid with nearest neighbor onto a ~30 m Web Mercator grid
so the ~2 x 3 km pixels keep their footprints.
"""

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import netCDF4
import numpy as np
from matplotlib.colors import Normalize
from rasterio.transform import Affine

from common import config, web
from visualize import CMAP, DATASET, FILE_GLOB, LST_RANGE, PAD_M, SOURCE, geos_crs, grid_transform, ground_footprint_m, parse_time


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    with netCDF4.Dataset(paths[-1]) as d:
        crs = geos_crs(d)
        transform, x, y = grid_transform(d)
        xmin, ymin, xmax, ymax = web.EXTENT_VIEW.bounds_in(crs, PAD_M)
        cols = np.nonzero((x >= xmin) & (x <= xmax))[0]
        rows = np.nonzero((y >= ymin) & (y <= ymax))[0]
        sl = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
        lst_k = d["LST"][sl].astype("float64").filled(np.nan)
        dqf = d["DQF"][sl].filled(3)
        t0, t1 = parse_time(d.time_coverage_start), parse_time(d.time_coverage_end)
        platform = d.platform_ID
    # region geos-to-web-grid
    lst = np.where((dqf <= 1) & np.isfinite(lst_k), lst_k - 273.15, np.nan)
    win_transform = transform * Affine.translation(cols[0], rows[0])
    v = web.EXTENT_VIEW
    ew, ns, vza = ground_footprint_m(crs, transform, v.lon, v.lat)
    grid = web.fine_grid(ew)
    data = web.reproject(lst, win_transform, crs, grid)
    # endregion geos-to-web-grid
    print(f"LST over the extent {np.nanmin(data):.1f} to {np.nanmax(data):.1f} degC; footprint {ew:.0f} x {ns:.0f} m")
    sources = {"lst": web.write_cog(DATASET, data, grid, ["lst"], max_z_error=0.01)}
    t_local = t0.astimezone(ZoneInfo("America/New_York"))
    when = f"{t0:%Y-%m-%d %H:%M}-{t1:%H:%M} UTC ({t_local:%H:%M} {t_local.tzname()})"
    products = {
        "lst": web.product(
            title=f"GOES-{platform[1:]} ABI land surface temperature (2 km)",
            subtitle=f"Scan {when}, view zenith {vza:.0f}°; ABI-L2-LSTC (CONUS); high and medium quality (DQF 0-1)",
            native=f"2 km at nadir, ~{ew / 1000:.1f} × {ns / 1000:.1f} km here",
            source=SOURCE,
            landmark_color="cyan",
            layers=[
                web.layer(
                    "lst",
                    web.colormap(CMAP, Normalize(*LST_RANGE), "Land surface temperature (°C)", band="lst", extend="both"),
                )
            ],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
