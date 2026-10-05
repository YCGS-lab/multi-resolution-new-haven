# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""CHIRPS v3 daily precipitation (0.05 deg) as a COG for the website: band
precip (mm/day), nearest-neighbor on a ~30 m Web Mercator grid so the cells
keep their footprints. Ocean cells are no data.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio

from common import web
from download import DATASET, DATE, output_path
from visualize import CMAP, NORM, SOURCE

NATIVE_M = 0.05 * 111320 * math.cos(math.radians(web.EXTENT_VIEW.lat))


def main():
    with rasterio.open(output_path()) as ds:
        precip, transform, crs = ds.read(1), ds.transform, ds.crs
    grid = web.fine_grid(NATIVE_M)
    data = web.reproject(precip, transform, crs, grid)
    print(f"precip over the extent {np.nanmin(data):.1f} to {np.nanmax(data):.1f} mm/day")
    sources = {"precip": web.write_cog(DATASET, data, grid, ["precip"], max_z_error=0.01)}
    products = {
        "precip": web.product(
            title="CHIRPS v3 daily precipitation",
            subtitle=f"{DATE:%Y-%m-%d} (daily total); land only (ocean cells transparent)",
            native="0.05° (~4 × 5.6 km here)",
            source=SOURCE,
            layers=[web.layer("precip", web.colormap(CMAP, NORM, "Precipitation (mm/day)", band="precip", extend="max"))],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
