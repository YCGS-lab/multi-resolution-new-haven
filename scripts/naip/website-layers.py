# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for NAIP, read live from the Microsoft Planetary Computer
(STAC collection `naip`, the contiguous US since 2010): the website lists the
NAIP years over the area in view from the STAC API, and reads the selected
year's DOQQs, mosaicked by the data API, as 8-bit images shown as they are
(no stretch). No local copy.

NAIP is flown every 2-3 years per state, at 1 m (to 2014), 0.6 m (2016-2021)
or 0.3 m (2022 on, in Connecticut from 2023).

Products: truecolor (R, G, B) and cir (NIR, R, G).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import web

DATASET = "naip"
SOURCE = "USDA FSA National Agriculture Imagery Program (NAIP), via Microsoft Planetary Computer"
NATIVE = "0.3-1 m, by year and state (0.3 m in Connecticut since 2023)"


def main():
    # region naip-live-source
    sources = {
        "truecolor": web.pc_mosaic_source("naip", {"r": "image|1", "g": "image|2", "b": "image|3"}, native_m=0.3, fmt="png"),
        "cir": web.pc_mosaic_source("naip", {"r": "image|4", "g": "image|1", "b": "image|2"}, native_m=0.3, fmt="png"),
    }
    meta = dict(
        time=web.time_spec("year", web.avail_stac("truecolor"), label="Year", widget="list"),
        coverage=web.CONUS,
        min_zoom=11,
    )
    # endregion naip-live-source
    products = {
        "truecolor": web.product(
            title="NAIP, true color",
            subtitle="Leaf-on aerial imagery, 4-band; 8-bit values shown as is",
            native=NATIVE,
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("truecolor", web.identity())],
        ),
        "cir": web.product(
            title="NAIP, color infrared (NIR, red, green)",
            subtitle="Leaf-on aerial imagery, 4-band; 8-bit values shown as is",
            native=NATIVE,
            source=SOURCE,
            layers=[web.layer("cir", web.identity())],
        ),
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
