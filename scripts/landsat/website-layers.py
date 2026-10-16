# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for Landsat 8-9 Collection 2 Level-2, read live from the
Microsoft Planetary Computer: the website lists the acquisition dates over
the area in view from the STAC API (with their scene cloud cover, for the
"max cloud cover" filter) and, for the selected date or date window, reads
raw tiles of a mosaic of the scenes from the data API (titiler), then applies
the Collection 2 scale factors and the render specs below. No local copy.

Composites use fixed stretches (surface reflectance), chosen from a summer
median over New Haven: the per-scene percentile stretches of
visualize-remote.py do not carry over to arbitrary dates and places.

Products: truecolor, cir, veg, urban, lst. (The Level-1 panchromatic band is
pre-built by create-cog.py: it is not on the Planetary Computer.)
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.colors import Normalize

from common import web

_spec = importlib.util.spec_from_file_location("visualize_remote", Path(__file__).parent / "visualize-remote.py")
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

DATASET = "landsat"
SOURCE = "Landsat 8-9 OLI/TIRS Collection 2 Level-2 (USGS), via Microsoft Planetary Computer"

# region live-stretches
# Reflectance ranges per band (R, G, B order of each composite)
STRETCH = {
    "truecolor": [(0.0, 0.3)] * 3,
    "cir": [(0.0, 0.5), (0.0, 0.3), (0.0, 0.3)],
    "veg": [(0.0, 0.45), (0.0, 0.5), (0.0, 0.3)],
    "urban": [(0.0, 0.4), (0.0, 0.45), (0.0, 0.3)],
}
LST_RANGE = (-10.0, 45.0)  # deg C, covers winter to summer afternoons
# endregion live-stretches
TITLES = {
    "truecolor": "Landsat 8-9 true color",
    "cir": "Landsat 8-9 color infrared",
    "veg": "Landsat 8-9 false color (vegetation)",
    "urban": "Landsat 8-9 false color (urban)",
}


def main():
    # region landsat-live-source
    sr = {a: vr.SR_SCALE for a in vr.ASSETS if a != "lwir11"}
    sources = {
        "l2": web.pc_mosaic_source(
            "landsat-c2-l2",
            {a: a for a in vr.ASSETS},
            native_m=30.0,
            scale={**sr, "lwir11": vr.ST_SCALE},
            offset={**{a: vr.SR_OFFSET for a in sr}, "lwir11": vr.ST_OFFSET - 273.15},
            nodata=0,
            query=[{"op": "in", "args": [{"property": "platform"}, ["landsat-8", "landsat-9"]]}],
        )
    }
    meta = dict(
        time=web.time_spec(
            "day",
            web.avail_stac("l2"),
            label="Acquisition date",
            window=web.window_spec(
                366,
                [
                    web.option(
                        "px",
                        "Pixel",
                        [("first", "Latest"), ("median", "Median"), ("mean", "Average")],
                        "median",
                        help="How scenes in the window are combined: the most recent valid pixel, "
                        "or the median / average of all scenes (fewer clouds)",
                    )
                ],
            ),
            filters=[web.filter_range("cc", "Max cloud cover", "eo:cloud_cover", 0, 100, 100, step=5, unit="%")],
        ),
        min_zoom=7,
    )
    # endregion landsat-live-source
    products = {}
    for product, (_, assets) in vr.COMPOSITES.items():
        g = vr.GAMMA[product]
        combo = ", ".join(vr.BAND_LABEL[a] for a in assets)
        products[product] = web.product(
            title=TITLES[product],
            subtitle=f"R, G, B = {combo}; surface reflectance",
            native="30 m",
            source=SOURCE,
            landmark_color="yellow" if product == "truecolor" else "white",
            layers=[web.layer("l2", web.rgb(*(web.channel(a, lo, hi, g) for a, (lo, hi) in zip(assets, STRETCH[product]))))],
        )
    products["lst"] = web.product(
        title="Landsat 8-9 land surface temperature",
        subtitle="TIRS B10 surface temperature (L2 ST_B10)",
        native="100 m TIRS, resampled to 30 m by USGS",
        source=SOURCE,
        landmark_color="cyan",
        layers=[web.layer("l2", web.colormap("inferno", Normalize(*LST_RANGE), "Land surface temperature (°C)", band="lwir11", extend="both"))],
    )
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
