# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Landsat 8 panchromatic band as a COG for the website (dataset landsat-pan):

  landsat-pan.tif  Level-1 panchromatic B8 (DN) on a 15 m grid, from the
                   subset saved by download.py (requester-pays AWS bucket,
                   which the website cannot read), for the one scene of
                   data/landsat/scene.json

The Level-2 products (truecolor, cir, veg, urban, lst) are read live by the
website; see website-layers.py.
Products: pan.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rasterio
from matplotlib.colors import Normalize

import download
import scene as scene_mod
from common import render, web

DATASET = scene_mod.DATASET
L1_SOURCE = "Landsat 8 OLI Collection 2 Level-1 (USGS), s3://usgs-landsat (requester pays)"
PAN_GAMMA = 1.5


def main():
    sc = scene_mod.load()
    when = f"{sc['date']} {sc['time_utc']} UTC"
    print(f"scene {sc['id']} ({when})")

    # Pan
    path = download.pan_path(sc)
    with rasterio.open(path) as ds:
        pan_dn, transform, crs, nodata = ds.read(1), ds.transform, ds.crs, ds.nodata
    pan_grid = web.fine_grid(15.0)
    pan = web.reproject(pan_dn, transform, crs, pan_grid, src_nodata=nodata)
    sources = {"pan": web.write_cog(f"{DATASET}-pan", pan, pan_grid, ["b8"], max_z_error=0.5)}

    lo, hi = render.percentiles(pan, 1, 99.5)
    print(f"pan: DN {lo:.0f} to {hi:.0f}")
    products = {
        "pan": web.product(
            title="Landsat 8 panchromatic (OLI band 8)",
            subtitle=f"B8 pan, 0.50-0.68 µm; Level-1 {sc['l1_product_id']}\n{when}",
            native="15 m",
            source=L1_SOURCE,
            landmark_color="yellow",
            layers=[web.layer("pan", web.colormap("gray", Normalize(lo, hi), band="b8", gamma=PAN_GAMMA))],
        )
    }
    meta = dict(time=web.snapshot_time(f"{sc['date']}T{sc['time_utc'][:5]}Z", "time", label="Acquired (UTC)"))
    web.write_spec(f"{DATASET}-pan", sources, products, meta)


if __name__ == "__main__":
    main()
