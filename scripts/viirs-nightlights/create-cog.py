# /// script
# requires-python = ">=3.11"
# dependencies = ["h5py", "numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""VIIRS Black Marble annual night lights (VNP46A4, 2025) as a COG for the
website: band radiance (nW cm-2 sr-1, NearNadir_Composite_Snow_Free; see
visualize.py), nearest-neighbor on a ~30 m Web Mercator grid so the
15 arc-second pixels keep their footprints. Shown on a log color scale
(values at or below its minimum, incl. 0 over water, take the lowest color).
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

from common import config, web
from visualize import CMAP, DATASET, FILE_GLOB, NORM, RES, SOURCE, read_subset

NATIVE_M = RES * 111320 * math.cos(math.radians(web.EXTENT_VIEW.lat))


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    rad, transform, attrs = read_subset(paths[-1])
    start, end = (a.decode() for a in (attrs["RangeBeginningDate"], attrs["RangeEndingDate"]))
    grid = web.fine_grid(NATIVE_M)
    data = web.reproject(rad, transform, "EPSG:4326", grid)
    print(f"radiance over the extent {np.nanmin(data):.2f} to {np.nanmax(data):.1f} nW/cm2/sr")
    sources = {"radiance": web.write_cog(DATASET, data, grid, ["radiance"], max_z_error=0.01)}
    products = {
        "radiance": web.product(
            title="VIIRS Black Marble night lights",
            subtitle=f"VNP46A4 annual composite {start[:4]} ({start} to {end}), near-nadir, snow-free",
            native="15 arc-seconds (~350 × 460 m here)",
            source=SOURCE,
            landmark_color="cyan",
            layers=[
                web.layer(
                    "radiance",
                    web.colormap(CMAP, NORM, "Radiance (nW cm$^{-2}$ sr$^{-1}$)", band="radiance", extend="min"),
                )
            ],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
