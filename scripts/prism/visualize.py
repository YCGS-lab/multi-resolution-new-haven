# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""PRISM 800 m monthly mean air temperature (tmean), July 2026.

Reads the clip written by download.py (NAD83 geographic, 30 arc-second
cells) and draws it on both views with one shared color range. Note that
PRISM's CONUS grid also covers Long Island Sound (water cells carry modeled
values); any nodata cells would be transparent.

Figures (per view): tmean.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from matplotlib.colors import Normalize

from common import config, render
from common.views import VIEWS

DATASET = "prism"
FILE = "prism_tmean_us_30s_202607_newhaven.tif"
CMAP = "RdYlBu_r"
RANGE = (22.75, 24.0)  # degC; data in the greater view span 22.9-23.8
SOURCE = "PRISM Group, Oregon State University (prism.oregonstate.edu), AN91 monthly tmean, provisional"


def main():
    with rasterio.open(config.data_dir(DATASET) / FILE) as src:
        data, transform, crs, nodata = src.read(1), src.transform, src.crs, src.nodata
    norm = Normalize(*RANGE)
    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(data, transform, crs, view, src_nodata=nodata)
        print(f"  tmean range in view {np.nanmin(grid):.2f} to {np.nanmax(grid):.2f} degC")
        render.save_figures(
            render.colorize(grid, CMAP, norm=norm), view, DATASET, "tmean",
            title="PRISM mean air temperature",
            subtitle="July 2026 monthly mean (provisional); 30 arc-second (~800 m) grid",
            colorbar=dict(cmap=CMAP, norm=norm, label="Mean air temperature (°C)", extend="both"),
            source=SOURCE,
        )  # fmt: skip


if __name__ == "__main__":
    main()
