# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""NISAR L2 GCOV dual-pol backscatter as a COG for the website: bands hh and hv
(RTC gamma0 in dB), fetched on the granule's native 10 m UTM grid from
titiler-cmr (as in visualize-remote.py) and put on a 10 m Web Mercator grid
with nearest neighbor.

The website computes the composites from the two bands (HH/HV ratio in dB =
hh - hv), with the channel ranges of visualize-remote.py. Stored locally
because titiler-cmr reads the HDF5 granule for every request, which is too
slow for interactive tiles.

Products: balanced, vegetation, urban, water (RGB), hh, hv (grayscale).
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from matplotlib.colors import Normalize
from rasterio.transform import from_origin

import granule as gr
from common import views, web

_spec = importlib.util.spec_from_file_location("visualize_remote", Path(__file__).parent / "visualize-remote.py")
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

DATASET = gr.DATASET
# region db-cog
EXPR = {"hh": "hh", "hv": "hv", "ratio": "hh - hv"}  # channel -> expression of the dB bands


def main():
    g = gr.load()
    print(f"granule {g['granule_ur']}")
    posting, crs = g["posting_m"], g["crs"]
    bounds = gr.snap_bounds(views.all_bounds_in(crs, vr.PAD_M), posting, g["grid_origin"])
    cov = gr.fetch_covariance(g["granule_ur"], bounds, crs, posting)
    transform = from_origin(bounds[0], bounds[3], posting, posting)
    grid = web.fine_grid(posting)
    hh, hv = web.reproject(cov, transform, crs, grid)
    with np.errstate(invalid="ignore", divide="ignore"):
        db = np.stack([10 * np.log10(hh), 10 * np.log10(hv)])
    db[~np.isfinite(db)] = np.nan
    print(f"valid fraction {np.isfinite(db).all(axis=0).mean():.3f}")
    sources = {"gcov": web.write_cog(DATASET, db, grid, ["hh", "hv"], max_z_error=0.01)}
# endregion db-cog

    t = g["time_at_view_center_utc"]
    when = f"{t[:10]} {t[11:16]} UTC, {g['pass'].lower()} pass (track {g['track']}, frame {g['frame']}), {g['look_direction'].lower()}-looking, incidence {g['incidence_angle_deg']:.0f}°"  # fmt: skip
    native = f"{posting:g} m posting, L-band frequency A ({g['bandwidth_a_mhz']:g} MHz)"
    products = {}
    for product, (title, chans) in vr.COMPOSITES.items():
        combo = ", ".join("{} [{:g}, {:g}]".format(vr.CHANNELS[c][0], *vr.CHANNELS[c][1]) for c in chans)
        channels = [web.channel(lo=vr.CHANNELS[c][1][0], hi=vr.CHANNELS[c][1][1], expr=EXPR[c]) for c in chans]
        products[product] = web.product(
            title=title,
            subtitle=f"R, G, B = {combo} dB; RTC γ⁰ backscatter\n{when}",
            native=native,
            source=vr.SOURCE,
            layers=[web.layer("gcov", web.rgb(*channels))],
        )
    for name in ("hh", "hv"):
        label, (lo, hi) = vr.CHANNELS[name]
        products[name] = web.product(
            title=f"NISAR L-band SAR: {label} backscatter",
            subtitle=f"{label} = 10 log10({name.upper() * 2}) (γ⁰, dB)\n{when}",
            native=native,
            source=vr.SOURCE,
            landmark_color="yellow",
            layers=[
                web.layer(
                    "gcov", web.colormap("gray", Normalize(lo, hi), f"{label} backscatter γ⁰ (dB)", band=name, extend="both")
                )
            ],
        )
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
