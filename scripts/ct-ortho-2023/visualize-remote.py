# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Connecticut statewide 2023 orthoimagery (3-inch / 0.0762 m = 0.25 ft,
4-band R/G/B/NIR, leaf-off, flown 2023-03-27 to 2023-04-13 by Dewberry for
the CT State GIS Office; UltraCam Eagle Mark 3), fetched as raw 8-bit band
values from the CT ECO Ortho_2023 ArcGIS ImageServer.

This is a different collection from NAIP 2023 (state-flown in spring with
the leaves off, ~4x finer). Acquisition dates per tile are not in the
service, so the subtitle gives the project's acquisition window from the
CT ECO metadata (cteco.uconn.edu/download/metadata/CT_ortho_2023_metadata.htm).

Each view is requested at 2x its pixel density (the server reads its
overview pyramid, 0.23/0.69/2.06/6.17 m levels, with bilinear interpolation)
and then 2x2 block-averaged, so the downsampling to the view grid averages
the fine imagery instead of aliasing. Both views use the same per-band
linear stretch + gamma (percentiles of both views pooled).

Figures (per view): truecolor (R, G, B) and cir (NIR, R, G false color).
"""

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from common import remote, render
from common.views import VIEWS

DATASET = "ct-ortho-2023"
SERVICE = "https://cteco.uconn.edu/ctraster/rest/services/images/Ortho_2023/ImageServer"
SOURCE = "CT State GIS Office 2023 statewide orthoimagery (Dewberry), via CT ECO Ortho_2023 image service (cteco.uconn.edu)"
NATIVE_M = 0.0762  # 3 inches
FLOWN = "2023-03-27 to 04-13"
OVERSAMPLE = 2
STRETCH_PCT = (0.5, 99.5)
GAMMA = 1.4  # brightens the (dark) vegetation; same for both views
PRODUCTS = {
    # product: (band indices into R, G, B, NIR; title)
    "truecolor": ([0, 1, 2], "Connecticut 2023 orthoimagery, true color"),
    "cir": ([3, 0, 1], "Connecticut 2023 orthoimagery, color infrared (NIR, red, green)"),
}


def fetch_bands(view) -> np.ndarray:
    """Raw (4, h, w) band values on the view grid, block-averaged from 2x oversampling."""
    fine = dataclasses.replace(view, width_px=view.width_px * OVERSAMPLE, height_px=view.height_px * OVERSAMPLE)
    a = remote.arcgis_export_image(
        SERVICE, fine, fmt="tiff", rendering_rule={"rasterFunction": "None"}, band_ids=[0, 1, 2, 3]
    ).astype("float32")
    b, h, w = a.shape
    return a.reshape(b, h // OVERSAMPLE, OVERSAMPLE, w // OVERSAMPLE, OVERSAMPLE).mean(axis=(2, 4))


def main():
    bands = {}
    for view in VIEWS.values():
        print(view.title)
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
            f"Flown {FLOWN} (leaf-off); "
            f"native 3 in ({NATIVE_M} m), 4-band; shown at {view.pixel_size_m:.1f} m/pixel"
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
