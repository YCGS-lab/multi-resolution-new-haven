# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""ASTER GDEM v3 (1 arc-second, ~30 m) as a COG for the website: bands
elevation (m) and hillshade (0-1, computed on the native 1" grid as in
visualize.py), both nearest-neighbor on a ~15 m Web Mercator grid so each
native pixel keeps its footprint.

Products: elevation (tinted, shaded by the hillshade band), hillshade.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from matplotlib.colors import Normalize

from common import render, styles, web
from visualize import DATASET, SOURCE, load_mosaic

NATIVE_M = 1 / 3600 * 110574  # N-S size of a 1 arc-second pixel (E-W ~23 m here)
NATIVE = "1 arc-second (~23 × 31 m here); global DEM from ASTER stereo, 2000-2013"


def main():
    dem, transform, crs = load_mosaic()
    lat = transform.f + transform.e * dem.shape[0] / 2
    dx = abs(transform.a) * 111320 * math.cos(math.radians(lat))
    dy = abs(transform.e) * 110574
    hs = np.where(np.isfinite(dem), render.hillshade(dem, dx, dy), np.nan)
    grid = web.fine_grid(NATIVE_M)
    data = web.reproject(np.stack([dem, hs]), transform, crs, grid)
    print(f"elevation over the extent {np.nanmin(data[0]):.0f} to {np.nanmax(data[0]):.0f} m")
    sources = {"dem": web.write_cog(DATASET, data, grid, ["elevation", "hillshade"], max_z_error=0.002)}
    norm = Normalize(*styles.ELEVATION_RANGE["greater"])
    products = {
        "elevation": web.product(
            title="ASTER GDEM v3 elevation",
            native=NATIVE,
            source=SOURCE,
            layers=[
                web.layer(
                    "dem",
                    web.colormap(
                        styles.ELEVATION_CMAP,
                        norm,
                        "Elevation (m)",
                        band="elevation",
                        extend=styles.ELEVATION_EXTEND,
                        shade=dict(band="hillshade", strength=0.5, precomputed=True),
                    ),
                )
            ],
        ),
        "hillshade": web.product(
            title="ASTER GDEM v3 hillshade",
            native=NATIVE,
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("dem", web.colormap("gray", Normalize(0, 1), band="hillshade"))],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
