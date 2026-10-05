# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""PRISM 800 m monthly mean air temperature (July 2026) as a COG for the
website: band tmean (deg C), nearest-neighbor on a ~30 m Web Mercator grid so
the 30 arc-second cells keep their footprints.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio
from matplotlib.colors import Normalize

from common import config, web
from visualize import CMAP, DATASET, FILE, RANGE, SOURCE

NATIVE_M = 30 / 3600 * 111320 * math.cos(math.radians(web.EXTENT_VIEW.lat))


def main():
    with rasterio.open(config.data_dir(DATASET) / FILE) as src:
        tmean, transform, crs, nodata = src.read(1), src.transform, src.crs, src.nodata
    grid = web.fine_grid(NATIVE_M)
    data = web.reproject(tmean, transform, crs, grid, src_nodata=nodata)
    print(f"tmean over the extent {np.nanmin(data):.2f} to {np.nanmax(data):.2f} degC")
    sources = {"tmean": web.write_cog(DATASET, data, grid, ["tmean"], max_z_error=0.001)}
    products = {
        "tmean": web.product(
            title="PRISM mean air temperature",
            subtitle="July 2026 monthly mean (provisional)",
            native="30 arc-seconds (~700 × 930 m here)",
            source=SOURCE,
            layers=[
                web.layer(
                    "tmean",
                    web.colormap(CMAP, Normalize(*RANGE), "Mean air temperature (°C)", band="tmean", extend="both"),
                )
            ],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
