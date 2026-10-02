# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""SMAP L4 root-zone soil moisture (9 km EASE-Grid 2.0) over New Haven, from
the subset written by download.py.

Figures (per view): sm_rootzone (m3/m3, 0-100 cm). Water / fill cells
(Long Island Sound) are transparent. Same color scale in both views.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio
from common import render
from common.views import VIEWS
from download import DATASET, output_path
from matplotlib.colors import Normalize

CMAP = "YlGnBu"
NORM = Normalize(0.15, 0.30)  # m3/m3, both views
SOURCE = "NASA SMAP L4 Global 3-hourly 9 km Surface and Root Zone Soil Moisture (SPL4SMGP v008), NSIDC DAAC"


def main():
    path = output_path()
    with rasterio.open(path) as ds:
        sm = ds.read(1)
        transform, crs, tags = ds.transform, ds.crs, ds.tags()
    t0 = dt.datetime.fromisoformat(tags["time_begin"].replace("Z", "+00:00"))
    t1 = dt.datetime.fromisoformat(tags["time_end"].replace("Z", "+00:00"))
    subtitle = f"{t0:%Y-%m-%d %H:%M}-{t1:%H:%M} UTC (3-hour mean); 9 km EASE-Grid 2.0 cells"
    print(f"{tags['granule']}: {np.isfinite(sm).sum()} of {sm.size} cells with data")
    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(sm, transform, crs, view)
        print(f"  range in view {np.nanmin(grid):.3f} to {np.nanmax(grid):.3f} m3/m3")
        render.save_figures(
            render.colorize(grid, CMAP, norm=NORM), view, DATASET, "sm_rootzone",
            title="SMAP L4 root-zone soil moisture (0-100 cm)",
            subtitle=subtitle,
            colorbar=dict(cmap=CMAP, norm=NORM, label="Soil moisture (m³/m³)", extend="both"),
            source=SOURCE,
        )  # fmt: skip


if __name__ == "__main__":
    main()
