# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for USGS 3DEP: the website reads raw elevation tiles straight
from the 3DEP ImageServer (exportImage, float32) and colors / hillshades
them itself, so there is no local copy.

Products: elevation (tinted + hillshade), hillshade (grayscale).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.colors import Normalize

from common import styles, web

DATASET = "3dep"
SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
SOURCE = "USGS 3D Elevation Program (3DEP) dynamic DEM, elevation.nationalmap.gov"
NATIVE = "~1 m lidar-derived (best available)"


def main():
    sources = {"dem": web.arcgis_source(SERVICE, native_m=1.0, bands=["elevation"], raw=True, nodata=-9999)}
    norm = Normalize(*styles.ELEVATION_RANGE["greater"])
    products = {
        "elevation": web.product(
            title="USGS 3DEP elevation",
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
                        shade=dict(band="elevation", strength=0.5),
                    ),
                )
            ],
        ),
        "hillshade": web.product(
            title="USGS 3DEP hillshade",
            native=NATIVE,
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("dem", web.colormap("gray", Normalize(0, 1), band="elevation", hillshade=True))],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
