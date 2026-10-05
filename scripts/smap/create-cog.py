# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""SMAP L4 root-zone soil moisture (9 km EASE-Grid 2.0) as a COG for the
website: band sm_rootzone (m3/m3), nearest-neighbor on a ~30 m Web Mercator
grid so the 9 km cells keep their footprints. Water cells are no data.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio

from common import web
from download import DATASET, output_path
from visualize import CMAP, NORM, SOURCE

NATIVE_M = 9008.0  # EASE-Grid 2.0 global 9 km cell


def main():
    with rasterio.open(output_path()) as ds:
        sm, transform, crs, tags = ds.read(1), ds.transform, ds.crs, ds.tags()
    t0 = dt.datetime.fromisoformat(tags["time_begin"].replace("Z", "+00:00"))
    t1 = dt.datetime.fromisoformat(tags["time_end"].replace("Z", "+00:00"))
    grid = web.fine_grid(NATIVE_M)
    data = web.reproject(sm, transform, crs, grid)
    print(f"sm_rootzone over the extent {np.nanmin(data):.3f} to {np.nanmax(data):.3f} m3/m3")
    sources = {"sm": web.write_cog(DATASET, data, grid, ["sm_rootzone"], max_z_error=0.0005)}
    products = {
        "sm_rootzone": web.product(
            title="SMAP L4 root-zone soil moisture (0-100 cm)",
            subtitle=f"{t0:%Y-%m-%d %H:%M}-{t1:%H:%M} UTC (3-hour mean); water cells transparent",
            native="9 km EASE-Grid 2.0 cells",
            source=SOURCE,
            layers=[web.layer("sm", web.colormap(CMAP, NORM, "Soil moisture (m³/m³)", band="sm_rootzone", extend="both"))],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
