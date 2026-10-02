# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""CHIRPS v3.0 daily precipitation (0.05 degree) over New Haven, from the
subset written by download.py.

Figures (per view): precip (mm/day). CHIRPS is land-only: ocean pixels are
nodata and shown transparent. Zero precipitation is valid data (lightest
color). Same color scale in both views.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio
from common import render
from common.views import VIEWS
from download import DATASET, DATE, output_path
from matplotlib.colors import Normalize

CMAP = "YlGnBu"
NORM = Normalize(0, 60)  # mm/day, both views
SOURCE = "CHIRPS v3.0 daily (final, IMERG-disaggregated), Climate Hazards Center, UC Santa Barbara"


def main():
    with rasterio.open(output_path()) as ds:
        precip = ds.read(1)
        transform, crs = ds.transform, ds.crs
    print(f"{np.isfinite(precip).sum()} of {precip.size} pixels with data, max {np.nanmax(precip):.1f} mm/day")
    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(precip, transform, crs, view)
        print(f"  range in view {np.nanmin(grid):.1f} to {np.nanmax(grid):.1f} mm/day")
        render.save_figures(
            render.colorize(grid, CMAP, norm=NORM), view, DATASET, "precip",
            title="CHIRPS v3 daily precipitation",
            subtitle=f"{DATE:%Y-%m-%d} (daily total); 0.05° (~5 km) grid",
            colorbar=dict(cmap=CMAP, norm=NORM, label="Precipitation (mm/day)", extend="max"),
            source=SOURCE,
        )  # fmt: skip


if __name__ == "__main__":
    main()
