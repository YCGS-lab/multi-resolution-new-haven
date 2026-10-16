# /// script
# requires-python = ">=3.11"
# dependencies = ["h5py", "numpy", "pyresample", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""Website layers for VIIRS daily land surface temperature (VNP21A1D v002,
Suomi NPP, daytime, 1 km sinusoidal grid), read live from LP DAAC's HDF5
tiles by this repository's tiler (tiler/, preset `viirs-lst-daily`), deployed
with Earthdata S3 credentials in AWS us-west-2 next to the data
(terraform/tiler; env.json `tiler`). It is cloud-only: locally it is shown
disabled with a cloud icon (or use `?cloud=1&service.tiler=...` with
tiler/serve-local.sh); the pre-built 750 m swath of 2026-06-03
(create-cog.py, "viirs-lst-prebuilt") still works locally.

VNP21A1D is the gridded daily version of the VNP21 swath used by the
figures (same TES algorithm): one value per 1 km cell from the day's
daytime overpasses, cloudy cells not produced. The website lists the days
with tiles over the area in view from CMR (public).

Products: lst.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from matplotlib.colors import Normalize

from common import web
from visualize import CMAP, DATASET, LST_RANGE

CONCEPT_ID = "C2545314555-LPCLOUD"  # VNP21A1D v002
SOURCE = "NASA VIIRS LST&E VNP21A1D v002 (Suomi NPP), LP DAAC"


def main():
    # region viirs-lst-live-source
    sources = {
        "lst": web.tiler_source(
            "viirs-lst-daily", ["LST_1KM"], native_m=926.6, time_param="interval", derive={"lst": "LST_1KM - 273.15"}
        )
    }
    meta = dict(
        time=web.time_spec("day", web.avail_cmr(CONCEPT_ID), label="Day (daytime overpass)", widget="calendar"),
        requires=web.requires_cloud("NASA Earthdata (LP DAAC) HDF5 in AWS us-west-2, read by a tiler next to the data", "tiler"),
        min_zoom=4,
    )
    # endregion viirs-lst-live-source
    products = {
        "lst": web.product(
            title="VIIRS land surface temperature (Suomi NPP, daily, 1 km)",
            subtitle="Daytime overpass (~13:30 local solar time); VNP21A1D v002; cloud and water transparent",
            native="1 km sinusoidal grid cells (926.6 m)",
            source=SOURCE,
            landmark_color="cyan",
            layers=[web.layer("lst", web.colormap(CMAP, Normalize(*LST_RANGE), "Land surface temperature (°C)", band="lst", extend="both"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
