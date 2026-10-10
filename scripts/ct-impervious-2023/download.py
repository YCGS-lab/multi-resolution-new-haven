# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "geopandas", "pyogrio", "shapely"]
# ///
"""Connecticut 2023 high-resolution impervious surface ("Land" polygon layer),
downloaded from the CT GIS Office ArcGIS Online FeatureServer.

Every polygon intersecting the (padded) greater view envelope is fetched in
EPSG:3857 and saved as a GeoPackage:
    data/ct-impervious-2023/impervious_2023_land.gpkg   (layer "impervious")

One query over the whole envelope (~370k features) paginated with resultOffset
takes ~30-60 s per page on the server, so the envelope is split into small
tiles, each paginated with resultOffset (fast, ~2 s per page); features that
cross tile edges are de-duplicated by OBJECTID. Pages are cached in
data/ct-impervious-2023/_pages/ so an interrupted run resumes.

Features are requested as Esri JSON rather than GeoJSON: the service's GeoJSON
output turns the holes of large polygons (e.g. town-wide road networks with
thousands of city-block holes) into extra overlapping parts. Esri rings are
assembled here by orientation (clockwise = exterior, counter-clockwise = hole).
"""

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import LinearRing, MultiPolygon, Polygon

from common import config, remote, views

DATASET = "ct-impervious-2023"
LAYER = (
    "https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/"
    "Impervious_Surface_Land_Connecticut_2023/FeatureServer/1"
)
PAGE = 2000  # service maxRecordCount
TILE_M = 1500.0  # query tile size (EPSG:3857 m)
PAD_M = 50.0
OUT_NAME = "impervious_2023_land.gpkg"


# region esri-ring-assembly
def rings_to_geometry(rings):
    """Esri JSON polygon rings -> shapely (Multi)Polygon."""
    shells, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        (holes if LinearRing(r).is_ccw else shells).append(r)
    if not shells:
        return Polygon()
    if len(shells) == 1:
        return Polygon(shells[0], holes)
    polys = [Polygon(s) for s in shells]
    tree = shapely.STRtree(polys)
    areas = np.array([p.area for p in polys])
    assigned = [[] for _ in shells]
    for h in holes:
        pt = shapely.Point(h[0])
        cands = [k for k in tree.query(pt) if polys[k].covers(pt)]
        if cands:
            assigned[min(cands, key=lambda k: areas[k])].append(h)
    return MultiPolygon([Polygon(s, hs) for s, hs in zip(shells, assigned)])
# endregion esri-ring-assembly


def main():
    out_dir = config.data_dir(DATASET)
    out = out_dir / OUT_NAME
    if out.exists():
        print(f"{out.relative_to(config.REPO)} exists; delete it to re-download", flush=True)
        return
    pages_dir = out_dir / "_pages"
    pages_dir.mkdir(exist_ok=True)

    # region tiled-paginated-query
    xmin, ymin, xmax, ymax = views.all_bounds_in(views.CRS, PAD_M)
    xs = np.linspace(xmin, xmax, int(np.ceil((xmax - xmin) / TILE_M)) + 1)
    ys = np.linspace(ymin, ymax, int(np.ceil((ymax - ymin) / TILE_M)) + 1)
    tiles = [(i, j, (xs[i], ys[j], xs[i + 1], ys[j + 1])) for j in range(len(ys) - 1) for i in range(len(xs) - 1)]
    print(f"envelope {xmax - xmin:.0f} x {ymax - ymin:.0f} m (EPSG:3857) -> {len(tiles)} query tiles", flush=True)
    sess = remote.session()

    def query(bounds, offset):
        params = {
            "geometry": ",".join(f"{v:.2f}" for v in bounds),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 3857,
            "spatialRel": "esriSpatialRelIntersects",
            "where": "1=1",
            "outSR": 3857,
            "outFields": "OBJECTID,CateTitle,TOWN_NAME",
            "geometryPrecision": 2,  # cm
            "orderByFields": "OBJECTID",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
            "f": "json",
        }
        for _ in range(4):
            r = sess.get(LAYER + "/query", params=params, timeout=300)
            r.raise_for_status()
            try:
                d = r.json()
            except json.JSONDecodeError:
                continue
            if "features" in d:
                return d
        raise RuntimeError(f"query failed for {bounds} offset {offset}: {r.text[:300]}")

    def fetch_tile(tile):
        i, j, bounds = tile
        done = pages_dir / f"{j:03d}_{i:03d}.done"
        if done.exists():
            return
        offset = 0
        while True:
            d = query(bounds, offset)
            (pages_dir / f"{j:03d}_{i:03d}_{offset:07d}.json").write_text(json.dumps(d))
            if not d.get("exceededTransferLimit"):
                break
            offset += PAGE
        done.touch()

    with ThreadPoolExecutor(6) as pool:
        for k, _ in enumerate(pool.map(fetch_tile, tiles), 1):
            if k % 20 == 0 or k == len(tiles):
                print(f"  {k}/{len(tiles)} tiles", flush=True)
    # endregion tiled-paginated-query

    records = {}
    for p in sorted(pages_dir.glob("*.json")):
        for f in json.loads(p.read_text())["features"]:
            a = f["attributes"]
            if a["OBJECTID"] not in records and f.get("geometry"):
                records[a["OBJECTID"]] = (a["CateTitle"], a["TOWN_NAME"], f["geometry"]["rings"])
    oids = sorted(records)
    gdf = gpd.GeoDataFrame(
        {
            "OBJECTID": oids,
            "CateTitle": [records[o][0] for o in oids],
            "TOWN_NAME": [records[o][1] for o in oids],
        },
        geometry=[rings_to_geometry(records[o][2]) for o in oids],
        crs=views.CRS,
    )
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
    print(f"{len(gdf)} unique features", flush=True)
    print(gdf["CateTitle"].value_counts().to_string(), flush=True)
    gdf.to_file(out, layer="impervious", driver="GPKG")
    shutil.rmtree(pages_dir)
    print(f"wrote {out.relative_to(config.REPO)} ({out.stat().st_size / 1e6:.0f} MB)", flush=True)


if __name__ == "__main__":
    main()
