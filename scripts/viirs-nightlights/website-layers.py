# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "h5py"]
# ///
"""Website layers for VIIRS Black Marble annual night lights (VNP46A4 v002,
15 arc-second HDF-EOS5 tiles), read live from LAADS's S3 bucket.

The public titiler-cmr deployment has no S3 access to LAADS (tested: S3
credential error), so the dataset is cloud-only: it needs a titiler-cmr style
service with Earthdata S3 credentials running in AWS us-west-2 next to the
website (env.json `earthdata_tiler`). Locally it is shown disabled with a
cloud icon; the pre-built 2025 snapshot (create-cog.py,
"viirs-nightlights-prebuilt") still works locally.

The years over the area in view come from CMR (public).

Products: radiance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import web
from visualize import CMAP, FIELD, GRID, NORM, RES, SOURCE

DATASET = "viirs-nightlights"
CONCEPT_ID = "C3860065683-LAADS"  # VNP46A4 v2


def main():
    # region nightlights-live-source
    sources = {
        "radiance": web.titiler_cmr_source(
            CONCEPT_ID, [FIELD], native_m=RES * 111320 * 0.75, group=f"{GRID}/Data Fields", service="earthdata_tiler",
            derive={"radiance": FIELD},
        )
    }
    meta = dict(
        time=web.time_spec("year", web.avail_cmr(CONCEPT_ID), label="Year", widget="list"),
        requires=web.requires_cloud("NASA Earthdata (LAADS) HDF5 in AWS us-west-2, read by a tiler next to the data", "earthdata_tiler"),
        min_zoom=6,
    )
    # endregion nightlights-live-source
    products = {
        "radiance": web.product(
            title="VIIRS Black Marble night lights",
            subtitle="VNP46A4 annual composite, near-nadir, snow-free",
            native="15 arc-seconds (~350 × 460 m at New Haven)",
            source=SOURCE,
            landmark_color="cyan",
            layers=[web.layer("radiance", web.colormap(CMAP, NORM, "Radiance (nW cm$^{-2}$ sr$^{-1}$)", band="radiance", extend="min"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
