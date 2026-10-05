# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for the Connecticut 2023 orthoimagery: the website requests
each tile from the CT ECO Ortho_2023 ImageServer (exportImage, JPEG of the
raw 8-bit bands) and shows the values as they are (no stretch), so there is
no local copy of the ~45-gigapixel mosaic.

Products: truecolor (R, G, B) and cir (NIR, R, G).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import web

DATASET = "ct-ortho-2023"
SERVICE = "https://cteco.uconn.edu/ctraster/rest/services/images/Ortho_2023/ImageServer"
SOURCE = "CT State GIS Office 2023 statewide orthoimagery (Dewberry), via CT ECO Ortho_2023 image service (cteco.uconn.edu)"
NATIVE_M = 0.0762  # 3 inches
SUBTITLE = "Flown 2023-03-27 to 04-13 (leaf-off); 4-band; server 8-bit values shown as is"
NATIVE = "3 in (0.076 m)"


def main():
    sources = {
        "truecolor": web.arcgis_source(SERVICE, NATIVE_M, band_ids=[0, 1, 2]),
        "cir": web.arcgis_source(SERVICE, NATIVE_M, band_ids=[3, 0, 1]),
    }
    products = {
        "truecolor": web.product(
            title="Connecticut 2023 orthoimagery, true color",
            subtitle=SUBTITLE,
            native=NATIVE,
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("truecolor", web.identity())],
        ),
        "cir": web.product(
            title="Connecticut 2023 orthoimagery, color infrared (NIR, red, green)",
            subtitle=SUBTITLE,
            native=NATIVE,
            source=SOURCE,
            layers=[web.layer("cir", web.identity())],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
