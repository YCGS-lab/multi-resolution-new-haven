# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "pystac-client", "planetary-computer", "shapely"]
# ///
"""Pick the Landsat 8 Collection 2 Level-2 scene used by every Landsat script.

Criteria: Landsat 8 (not 9), scene covers both views, acquired in the green
season (May 20 - Sep 30), scene cloud cover < 5 %, and the (padded) greater
view itself is free of cloud / cloud shadow according to QA_PIXEL. The most
recent scene that passes wins. Writes data/landsat/scene.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.windows import from_bounds as window_from_bounds
from shapely.geometry import box, shape

from common import config, views

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
# USGS LandsatLook STAC, for the matching Collection 2 Level-1 product (pan band)
L1_STAC = "https://landsatlook.usgs.gov/stac-server"
L1_COLLECTION = "landsat-c2l1"
COLLECTION = "landsat-c2-l2"
SEASON = ((5, 20), (9, 30))  # (month, day) start / end of the green season
MAX_SCENE_CLOUD = 5.0
MAX_VIEW_CLOUD = 0.001  # fraction of view pixels flagged cloud / shadow / cirrus
PAD_M = 300.0
# QA_PIXEL bits: 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow
CLOUD_BITS = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)


def in_season(dt: str) -> bool:
    md = (int(dt[5:7]), int(dt[8:10]))
    return SEASON[0] <= md <= SEASON[1]


def view_cloud_fraction(item) -> tuple[float, float]:
    """(cloud fraction, fill fraction) of QA_PIXEL over the padded greater view."""
    href = planetary_computer.sign(item.assets["qa_pixel"].href)
    with rasterio.open(href) as ds:
        b = views.all_bounds_in(ds.crs, PAD_M)
        win = window_from_bounds(*b, ds.transform).round_offsets().round_lengths()
        qa = ds.read(1, window=win)
    fill = (qa & 1).astype(bool)
    cloud = (qa & CLOUD_BITS) > 0
    return float(cloud[~fill].mean()) if (~fill).any() else 1.0, float(fill.mean())


def find_l1(item) -> dict:
    """The Level-1 item for the same Landsat 8 path/row/date (USGS LandsatLook STAC)."""
    p = item.properties
    date = p["datetime"][:10]
    cat = pystac_client.Client.open(L1_STAC)
    search = cat.search(
        collections=[L1_COLLECTION],
        bbox=views.all_bounds_lonlat(),
        datetime=f"{date}T00:00:00Z/{date}T23:59:59Z",
        query={"platform": {"eq": "LANDSAT_8"}},
    )
    for l1 in search.items():
        q = l1.properties
        if (q["landsat:wrs_path"], q["landsat:wrs_row"]) == (p["landsat:wrs_path"], p["landsat:wrs_row"]):
            pan = l1.assets["pan"]
            return {
                "l1_product_id": l1.id,
                "l1_stac_api": L1_STAC,
                "l1_stac_collection": L1_COLLECTION,
                "l1_pan_s3": pan.extra_fields["alternate"]["s3"]["href"],
                "l1_mtl_json_s3": l1.assets["MTL.json"].extra_fields["alternate"]["s3"]["href"],
            }
    raise SystemExit(f"no Level-1 product found for {item.id}")


def main():
    w, s, e, n = views.all_bounds_lonlat(PAD_M)
    aoi = box(w, s, e, n)
    cat = pystac_client.Client.open(STAC)
    search = cat.search(
        collections=[COLLECTION],
        bbox=[w, s, e, n],
        query={"platform": {"eq": "landsat-8"}, "eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
        sortby=[{"field": "datetime", "direction": "desc"}],
    )
    for item in search.items():
        dt = item.properties["datetime"]
        if not in_season(dt):
            continue
        if not shape(item.geometry).contains(aoi):
            print(f"{item.id}: does not cover both views")
            continue
        cloud, fill = view_cloud_fraction(item)
        print(f"{item.id}: scene cloud {item.properties['eo:cloud_cover']}%, view cloud {100 * cloud:.2f}%, fill {100 * fill:.2f}%")
        if cloud > MAX_VIEW_CLOUD or fill > 0:
            continue
        p = item.properties
        scene = {
            "id": item.id,
            "datetime": dt,
            "date": dt[:10],
            "time_utc": dt[11:16],
            "platform": p["platform"],
            "wrs_path": p["landsat:wrs_path"],
            "wrs_row": p["landsat:wrs_row"],
            "collection_category": p["landsat:collection_category"],
            "scene_id": p["landsat:scene_id"],
            "eo_cloud_cover": p["eo:cloud_cover"],
            "view_cloud_fraction": cloud,
            "crs": p["proj:code"],
            "stac_collection": COLLECTION,
            "stac_api": STAC,
            # Level-2 product id incl. processing date, e.g. LC08_L2SP_013031_20240912_20240920_02_T1
            "l2_product_id": Path(item.assets["red"].href).name.rsplit("_SR_B4", 1)[0],
            **find_l1(item),
        }
        out = config.data_dir("landsat") / "scene.json"
        out.write_text(json.dumps(scene, indent=2) + "\n")
        print(f"selected {item.id} -> {out.relative_to(config.REPO)}")
        return
    raise SystemExit("no scene passed the criteria")


if __name__ == "__main__":
    main()
