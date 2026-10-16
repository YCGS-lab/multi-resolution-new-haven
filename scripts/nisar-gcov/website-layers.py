# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for NISAR L2 GCOV dual-pol backscatter, read live through
the public titiler-cmr deployment (NASA VEDA, env.json's `titiler_cmr`;
xarray backend), which opens the HDF5 granules in ASF's S3 bucket from inside
AWS us-west-2. Works locally and online; tiles are slow (5-10 s each: every
request opens the granules).

The website lists the acquisition dates over the area in view from CMR
(public), and mosaics the granules of the selected day, or of a window of
days (latest pixel, median or average), from raw HHHH / HVHV tiles, in dB:
  HH = 10 log10(HHHH), HV = 10 log10(HVHV), HH/HV = HH - HV
with the channel ranges of visualize-remote.py.

Products: balanced, vegetation, urban, water (RGB), hh, hv (grayscale).
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from matplotlib.colors import Normalize

import granule as gr
from common import web

_spec = importlib.util.spec_from_file_location("visualize_remote", Path(__file__).parent / "visualize-remote.py")
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

DATASET = gr.DATASET
SOURCE = "NISAR L2 GCOV provisional (NASA JPL / ISRO), ASF DAAC; via titiler-cmr (Development Seed / NASA VEDA)"
EXPR = {"hh": "hh", "hv": "hv", "ratio": "hh - hv"}  # channel -> expression of the dB bands
NATIVE = "10 m posting, L-band frequency A (20 MHz)"


def main():
    # region nisar-live-source
    sources = {
        "gcov": web.titiler_cmr_source(
            gr.COLLECTION_CONCEPT_ID,
            gr.VARIABLES,
            native_m=10.0,
            group=gr.GROUP,
            derive={"hh": "10 * log10(HHHH)", "hv": "10 * log10(HVHV)"},
        )
    }
    meta = dict(
        time=web.time_spec(
            "day",
            web.avail_cmr(gr.COLLECTION_CONCEPT_ID),
            label="Acquisition date",
            window=web.window_spec(
                90,
                [
                    web.option(
                        "px",
                        "Pixel",
                        [("first", "Latest"), ("median", "Median"), ("mean", "Average")],
                        "first",
                        help="How acquisitions in the window are combined (median / average reduce speckle)",
                    )
                ],
            ),
        ),
        min_zoom=9,
    )
    # endregion nisar-live-source
    products = {}
    for product, (title, chans) in vr.COMPOSITES.items():
        combo = ", ".join("{} [{:g}, {:g}]".format(vr.CHANNELS[c][0], *vr.CHANNELS[c][1]) for c in chans)
        channels = [web.channel(lo=vr.CHANNELS[c][1][0], hi=vr.CHANNELS[c][1][1], expr=EXPR[c]) for c in chans]
        products[product] = web.product(
            title=title,
            subtitle=f"R, G, B = {combo} dB; RTC γ⁰ backscatter",
            native=NATIVE,
            source=SOURCE,
            layers=[web.layer("gcov", web.rgb(*channels))],
        )
    for name in ("hh", "hv"):
        label, (lo, hi) = vr.CHANNELS[name]
        products[name] = web.product(
            title=f"NISAR L-band SAR: {label} backscatter",
            subtitle=f"{label} = 10 log10({name.upper() * 2}) (γ⁰, dB)",
            native=NATIVE,
            source=SOURCE,
            landmark_color="yellow",
            layers=[
                web.layer("gcov", web.colormap("gray", Normalize(lo, hi), f"{label} backscatter γ⁰ (dB)", band=name, extend="both"))
            ],
        )
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
