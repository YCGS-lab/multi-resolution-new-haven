# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for NAIP 2023: the website requests each tile from the CT ECO
NAIP_2023 ImageServer (exportImage, JPEG of the raw 8-bit bands) and shows the
values as they are (no stretch), so there is no local copy.

The subtitle lists the acquisition dates of the NAIP DOQQs over the extent
(from the service catalog; see visualize-remote.py).

Products: truecolor (R, G, B) and cir (NIR, R, G).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import remote, web

DATASET = "naip"
SERVICE = "https://cteco.uconn.edu/ctraster/rest/services/images/NAIP_2023/ImageServer"
SOURCE = "USDA FSA National Agriculture Imagery Program (NAIP) 2023, via CT ECO NAIP_2023 image service (cteco.uconn.edu)"
NATIVE_M = 0.3


def acquisition_dates() -> list[str]:
    """Acquisition dates (YYYY-MM-DD) of the NAIP DOQQs intersecting the extent."""
    r = remote.session().get(
        SERVICE + "/query",
        params={
            "where": "Category=1",
            "geometry": ",".join(f"{v:.0f}" for v in web.EXTENT_VIEW.bounds),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 3857,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "Name",
            "returnGeometry": "false",
            "f": "json",
        },
        timeout=60,
    )
    r.raise_for_status()
    names = [f["attributes"]["Name"] for f in r.json()["features"]]
    print(f"  {len(names)} DOQQs: {', '.join(sorted(names))}")
    dates = {m.group(1) for n in names if (m := re.search(r"_(\d{8})_\d{8}$", n))}
    return sorted(f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates)


def main():
    dates = acquisition_dates()
    flown = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1][5:]}"
    subtitle = f"Flown {flown} (leaf-on); 4-band; server 8-bit values shown as is"
    sources = {
        "truecolor": web.arcgis_source(SERVICE, NATIVE_M, band_ids=[0, 1, 2]),
        "cir": web.arcgis_source(SERVICE, NATIVE_M, band_ids=[3, 0, 1]),
    }
    products = {
        "truecolor": web.product(
            title="NAIP 2023, true color",
            subtitle=subtitle,
            native="0.3 m",
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("truecolor", web.identity())],
        ),
        "cir": web.product(
            title="NAIP 2023, color infrared (NIR, red, green)",
            subtitle=subtitle,
            native="0.3 m",
            source=SOURCE,
            layers=[web.layer("cir", web.identity())],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
