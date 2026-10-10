# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""NISAR L2 GCOV (provisional) L-band dual-pol SAR backscatter: RGB
composites and HH / HV images.

Raw HHHH and HVHV covariance terms (RTC gamma0, linear power) of frequency A
are fetched from titiler-cmr (xarray backend) on the granule's native 10 m
UTM grid, for the one granule in data/nisar-gcov/granule.json (from
select_granule.py), then put on each view's grid with nearest neighbor and
converted to dB locally. The RGB channel definitions and dB ranges are those
of the titiler-cmr-browser NISAR GCOV renders (b1 = HHHH, b2 = HVHV):
  HH = 10 log10(b1)      [-20, 0] dB
  HV = 10 log10(b2)      [-30, 5] dB
  HH/HV = 10 log10(b1/b2) [2, 18] dB

Products: balanced, vegetation, urban, water (RGB), hh, hv (grayscale).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from matplotlib.colors import Normalize
from rasterio.transform import from_origin

import granule as gr
from common import render, views
from common.views import VIEWS

DATASET = gr.DATASET
SOURCE = (
    "NISAR L2 GCOV provisional (NASA JPL / ISRO), ASF DAAC; "
    "via titiler-cmr (Development Seed / NASA VEDA)"
)
PAD_M = 30.0  # > 1 native pixel

# region db-channel-ranges
# channel: (label, dB range)
CHANNELS = {
    "hh": ("HH", (-20.0, 0.0)),
    "hv": ("HV", (-30.0, 5.0)),
    "ratio": ("HH/HV", (2.0, 18.0)),
}
COMPOSITES = {
    # product: (title, channels as R, G, B)
    "balanced": ("NISAR L-band SAR: balanced dual-pol RGB", ("hh", "hv", "ratio")),
    "vegetation": ("NISAR L-band SAR: vegetation / volume emphasis", ("hv", "hh", "ratio")),
    "urban": ("NISAR L-band SAR: urban / built structure emphasis", ("ratio", "hh", "hv")),
    "water": ("NISAR L-band SAR: water / smooth surface emphasis", ("hv", "ratio", "hh")),
}


def channels_db(hh, hv) -> dict[str, np.ndarray]:
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"hh": 10 * np.log10(hh), "hv": 10 * np.log10(hv), "ratio": 10 * np.log10(hh / hv)}
# endregion db-channel-ranges


def main():
    g = gr.load()
    print(f"granule {g['granule_ur']}")
    posting, crs = g["posting_m"], g["crs"]

    # One fetch on the native grid serves both views (the greater view contains the central one).
    bounds = gr.snap_bounds(views.all_bounds_in(crs, PAD_M), posting, g["grid_origin"])
    cov = gr.fetch_covariance(g["granule_ur"], bounds, crs, posting)
    transform = from_origin(bounds[0], bounds[3], posting, posting)
    print(f"  valid fraction {np.mean(np.all(np.isfinite(cov), axis=0)):.4f}")

    t = g["time_at_view_center_utc"]
    when = f"{t[:10]} {t[11:16]} UTC, {g['pass'].lower()} pass (track {g['track']}, frame {g['frame']}), {g['look_direction'].lower()}-looking, incidence {g['incidence_angle_deg']:.0f}°"  # fmt: skip
    grid = f"L-band frequency A ({g['bandwidth_a_mhz']:g} MHz), {posting:g} m posting; RTC γ⁰ backscatter"

    for view in VIEWS.values():
        print(view.title)
        hh, hv = render.reproject_to_view(cov, transform, crs, view)  # nearest (10 m > output pixels)
        db = channels_db(hh, hv)
        for name, (label, (lo, hi)) in CHANNELS.items():
            d = db[name][np.isfinite(db[name])]
            print(f"  {label}: median {np.median(d):.1f} dB, 2-98% {np.percentile(d, 2):.1f} .. {np.percentile(d, 98):.1f} dB")

        for product, (title, chans) in COMPOSITES.items():
            rgb = np.stack([render.stretch(db[c], *CHANNELS[c][1]) for c in chans])
            combo = ", ".join("{} [{:g}, {:g}]".format(CHANNELS[c][0], *CHANNELS[c][1]) for c in chans)
            render.save_figures(
                render.to_rgba(rgb), view, DATASET, product,
                title=title,
                subtitle=f"R, G, B = {combo} dB\n{when}\n{grid}",
                source=SOURCE,
                landmark_color="white",
            )  # fmt: skip

        for name in ("hh", "hv"):
            label, (lo, hi) = CHANNELS[name]
            norm = Normalize(lo, hi)
            render.save_figures(
                render.colorize(db[name], "gray", norm=norm), view, DATASET, name,
                title=f"NISAR L-band SAR: {label} backscatter",
                subtitle=f"{label} = 10 log10({name.upper() * 2}) (γ⁰, dB)\n{when}\n{grid}",
                colorbar=dict(cmap="gray", norm=norm, label=f"{label} backscatter γ⁰ (dB)", extend="both"),
                source=SOURCE,
                landmark_color="yellow",
            )  # fmt: skip


if __name__ == "__main__":
    main()
