# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Landsat 8 OLI panchromatic band (B8, 15 m, Collection 2 Level-1), from the
subset saved by download.py. Grayscale percentile stretch, computed on the
greater view and applied to both views.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rasterio

import download
import scene as scene_mod
from common import render
from common.views import VIEWS

DATASET = scene_mod.DATASET
SOURCE = "Landsat 8 OLI Collection 2 Level-1 (USGS), s3://usgs-landsat (requester pays)"
GAMMA = 1.5


def main():
    sc = scene_mod.load()
    path = download.pan_path(sc)
    if not path.exists():
        raise SystemExit(f"{path} missing; run scripts/landsat/download.py first")
    with rasterio.open(path) as ds:
        pan, transform, crs, nodata = ds.read(1), ds.transform, ds.crs, ds.nodata

    grids = {v.name: render.reproject_to_view(pan, transform, crs, v, src_nodata=nodata) for v in VIEWS.values()}
    lo, hi = render.percentiles(grids["greater"], 1, 99.5)
    print(f"stretch DN {lo:.0f} - {hi:.0f}")
    when = f"{sc['date']} {sc['time_utc']} UTC"
    for view in VIEWS.values():
        print(view.title)
        gray = render.stretch(grids[view.name], lo, hi, GAMMA)
        render.save_figures(
            render.colorize(gray, "gray", 0, 1), view, DATASET, "pan",
            title="Landsat 8 panchromatic (OLI band 8)",
            subtitle=f"B8 pan, 0.50-0.68 µm; Level-1 {sc['l1_product_id']}\n{when}; 15 m pixels",
            source=SOURCE,
            landmark_color="yellow",
        )  # fmt: skip


if __name__ == "__main__":
    main()
