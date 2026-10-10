# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""USDA NAIP 2023 aerial imagery for Connecticut (0.3 m, 4-band R/G/B/NIR,
leaf-on, flown July 2023), fetched as raw 8-bit band values from the CT ECO
NAIP_2023 ArcGIS ImageServer.

The CT ECO service is a seamless mosaic of the standard USDA NAIP DOQQs
(catalog items are named like m_4107241_ne_18_030_20230705_20231113, the
USDA naming: quarter quad, UTM zone 18, 0.30 m, acquired 2023-07-05). It is
used instead of the Planetary Computer `naip` collection because it serves
the same DOQQs already mosaicked, as raw values, through the same
exportImage interface used for the CT 2023 orthoimagery.

Each view is requested at 2x its pixel density (the server reads its
overviews with bilinear interpolation) and then 2x2 block-averaged, so the
downsampling to the view grid averages the fine imagery instead of aliasing.
Both views use the same per-band linear stretch + gamma (percentiles of
both views pooled).

Figures (per view): truecolor (R, G, B) and cir (NIR, R, G false color).
"""

import dataclasses
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from common import remote, render
from common.views import VIEWS

DATASET = "naip"
SERVICE = "https://cteco.uconn.edu/ctraster/rest/services/images/NAIP_2023/ImageServer"
SOURCE = "USDA FSA National Agriculture Imagery Program (NAIP) 2023, via CT ECO NAIP_2023 image service (cteco.uconn.edu)"
NATIVE_M = 0.3
OVERSAMPLE = 2
STRETCH_PCT = (0.5, 99.5)
GAMMA = 1.15  # brightens the (dark) vegetation; same for both views
PRODUCTS = {
    # product: (band indices into R, G, B, NIR; title)
    "truecolor": ([0, 1, 2], "NAIP 2023, true color"),
    "cir": ([3, 0, 1], "NAIP 2023, color infrared (NIR, red, green)"),
}


# region oversample-block-average
def fetch_bands(view) -> np.ndarray:
    """Raw (4, h, w) band values on the view grid, block-averaged from 2x oversampling."""
    fine = dataclasses.replace(view, width_px=view.width_px * OVERSAMPLE, height_px=view.height_px * OVERSAMPLE)
    a = remote.arcgis_export_image(
        SERVICE, fine, fmt="tiff", rendering_rule={"rasterFunction": "None"}, band_ids=[0, 1, 2, 3]
    ).astype("float32")
    b, h, w = a.shape
    return a.reshape(b, h // OVERSAMPLE, OVERSAMPLE, w // OVERSAMPLE, OVERSAMPLE).mean(axis=(2, 4))
# endregion oversample-block-average


def acquisition_dates(view) -> list[str]:
    """Acquisition dates (YYYY-MM-DD) of the NAIP DOQQs intersecting the view."""
    r = remote.session().get(
        SERVICE + "/query",
        params={
            "where": "Category=1",
            "geometry": ",".join(f"{v:.0f}" for v in view.bounds),
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


def date_range(dates: list[str]) -> str:
    return dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1][5:]}"


def main():
    bands, dates = {}, {}
    for view in VIEWS.values():
        print(view.title)
        dates[view.name] = acquisition_dates(view)
        bands[view.name] = fetch_bands(view)

    # One stretch per band for both views.
    lims = []
    for i in range(4):
        pooled = np.concatenate([bands[v][i].ravel() for v in VIEWS])
        lims.append(np.percentile(pooled, STRETCH_PCT))
    print("stretch (R, G, B, NIR):", [tuple(round(float(x), 1) for x in l) for l in lims])

    for view in VIEWS.values():
        print(view.title)
        subtitle = (
            f"Flown {date_range(dates[view.name])} (leaf-on); "
            f"native {NATIVE_M} m, 4-band; shown at {view.pixel_size_m:.1f} m/pixel"
        )
        for product, (idx, title) in PRODUCTS.items():
            rgb = np.stack([render.stretch(bands[view.name][i], *lims[i], gamma=GAMMA) for i in idx])
            render.save_figures(
                render.to_rgba(rgb), view, DATASET, product,
                title=title,
                subtitle=subtitle,
                source=SOURCE,
                landmark_color="yellow" if product == "truecolor" else "white",
            )  # fmt: skip


if __name__ == "__main__":
    main()
