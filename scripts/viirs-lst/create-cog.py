# /// script
# requires-python = ">=3.11"
# dependencies = ["h5py", "numpy", "pyresample", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""VIIRS 750 m land surface temperature (VNP21 v002) as a COG for the website:
band lst (deg C; best and nominal QA, as in visualize.py). The L2 swath is
resampled onto a ~30 m Web Mercator grid by nearest neighbor (pyresample
kd-tree, as in visualize.py), so each ~750 m swath pixel keeps its footprint
(the Voronoi cell of its center).
"""

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from matplotlib.colors import Normalize
from pyresample import geometry, kd_tree

from common import config, web
from common.views import CRS
from visualize import CMAP, DATASET, FILE_GLOB, LST_RANGE, SOURCE, overpass_time, pixel_spacing_m, read_subset


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    # region swath-to-web-grid
    lst, qa, lat, lon, vza, row, attrs = read_subset(paths[-1])
    d_scan, d_track = pixel_spacing_m(lat, lon)
    radius = 0.6 * np.hypot(d_scan, d_track)
    grid = web.fine_grid(min(d_scan, d_track))
    area = geometry.AreaDefinition("web", "website grid", "web", CRS, grid.width, grid.height, grid.bounds)
    swath = geometry.SwathDefinition(lons=lon, lats=lat)
    data = kd_tree.resample_nearest(swath, lst, area, radius_of_influence=radius, fill_value=np.nan, epsilon=0)
    print(f"LST over the extent {np.nanmin(data):.1f} to {np.nanmax(data):.1f} degC ({np.isfinite(data).mean():.0%} valid)")
    sources = {"lst": web.write_cog(DATASET, data.astype("float32"), grid, ["lst"], max_z_error=0.01)}
    # endregion swath-to-web-grid
    t = overpass_time(attrs, row).replace(second=0, microsecond=0)
    t_local = t.astimezone(ZoneInfo("America/New_York"))
    when = f"{t:%Y-%m-%d %H:%M} UTC ({t_local:%H:%M} {t_local.tzname()})"
    products = {
        "lst": web.product(
            title="VIIRS land surface temperature (Suomi NPP, 750 m)",
            subtitle=f"{when}, view angle {vza.min():.1f}-{vza.max():.1f}°; VNP21 v002; best and nominal QA (cloud and water transparent)",
            native=f"750 m M-band swath pixels (~{d_scan:.0f} × {d_track:.0f} m here; nearest neighbor)",
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
