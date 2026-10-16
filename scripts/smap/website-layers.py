# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for SMAP L4 root-zone soil moisture (SPL4SMGP, 3-hourly,
9 km EASE-Grid 2.0), read live from the HDF5 granules in NSIDC's S3 bucket.

The public titiler-cmr deployment cannot open these granules (tested: "file
signature not found": it opens each granule's `.qa` text file), so the
dataset is read by this repository's tiler (tiler/, preset `smap-l4`),
deployed with Earthdata S3 credentials in AWS us-west-2 next to the data
(terraform/tiler; env.json `tiler`). It is cloud-only: locally it is shown
disabled with a cloud icon (or use `?cloud=1&service.tiler=...` with
tiler/serve-local.sh); the pre-built snapshot of one 3-hour mean
(create-cog.py, "smap-prebuilt") still works locally.

The website lists the 3-hourly granules over the area in view from CMR
(public): a calendar plus a time-of-day drop-down.

Products: sm_rootzone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import web
from visualize import CMAP, NORM, SOURCE

DATASET = "smap"
CONCEPT_ID = "C3480440870-NSIDC_CPRD"  # SPL4SMGP v008


def main():
    # region smap-live-source
    sources = {
        "sm": web.tiler_source("smap-l4", ["sm_rootzone"], native_m=9008.0, time_param="interval")
    }
    meta = dict(
        time=web.time_spec("time", web.avail_cmr(CONCEPT_ID), label="3-hour mean from (UTC)", widget="calendar"),
        requires=web.requires_cloud("NASA Earthdata (NSIDC) HDF5 in AWS us-west-2, read by a tiler next to the data", "tiler"),
        min_zoom=4,
    )
    # endregion smap-live-source
    products = {
        "sm_rootzone": web.product(
            title="SMAP L4 root-zone soil moisture (0-100 cm)",
            subtitle="3-hour mean; water cells transparent",
            native="9 km EASE-Grid 2.0 cells",
            source=SOURCE,
            layers=[web.layer("sm", web.colormap(CMAP, NORM, "Soil moisture (m³/m³)", band="sm_rootzone", extend="both"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
