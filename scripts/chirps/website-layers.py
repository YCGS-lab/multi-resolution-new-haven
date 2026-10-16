# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for CHIRPS v3.0 daily precipitation (final,
IMERG-disaggregated, 0.05 deg), read live from the Climate Hazards Center's
daily COGs by this repository's tiler (tiler/, preset `chirps-daily`;
env.json `tiler`). The COGs are served without CORS headers, so browsers
cannot read them directly: the dataset is cloud-only, and the pre-built day
(create-cog.py, "chirps-prebuilt") still works locally.

Every day since 2000 can be picked, up to ~45 days ago (the "final" stream
is published about a month after the month ends).

Products: precip.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import web
from download import DATASET
from visualize import CMAP, NORM, SOURCE

NATIVE_M = 0.05 * 111320 * math.cos(math.radians(web.EXTENT_VIEW.lat))


def main():
    # region chirps-live-source
    sources = {"precip": web.tiler_source("chirps-daily", ["precip"], native_m=NATIVE_M)}
    meta = dict(
        time=web.time_spec("day", web.avail_range("day", "2000-01-01", latency_hours=45 * 24), label="Day", widget="calendar"),
        requires=web.requires_cloud("Climate Hazards Center COGs without CORS headers, read by a tiler", "tiler"),
        coverage=web.coverage(-180.0, -60.0, 180.0, 60.0, "60° S to 60° N"),
        min_zoom=3,
    )
    # endregion chirps-live-source
    products = {
        "precip": web.product(
            title="CHIRPS v3 daily precipitation",
            subtitle="Daily total; land only (ocean cells transparent)",
            native="0.05° (~4 × 5.6 km here)",
            source=SOURCE,
            layers=[web.layer("precip", web.colormap(CMAP, NORM, "Precipitation (mm/day)", band="precip", extend="max"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
