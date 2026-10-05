# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Landsat 8 as COGs for the website:

  landsat.tif      Collection 2 Level-2 bands on a 30 m Web Mercator grid
                   (nearest neighbor, from the Microsoft Planetary Computer data
                   API as in visualize-remote.py): surface reflectance red,
                   green, blue, nir08, swir16, swir22 and surface temperature
                   lwir11 (deg C)
  landsat-pan.tif  Level-1 panchromatic B8 (DN) on a 15 m grid, from the
                   subset saved by download.py

The website builds the composites from the bands with the stretches below
(percentiles over the extent, as in the visualize scripts).
Products: truecolor, cir, veg, urban, lst, pan.
"""

import importlib.util
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import rasterio
from matplotlib.colors import Normalize
from rasterio.io import MemoryFile

import download
import scene as scene_mod
from common import remote, render, web

_spec = importlib.util.spec_from_file_location("visualize_remote", Path(__file__).parent / "visualize-remote.py")
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

DATASET = scene_mod.DATASET
L1_SOURCE = "Landsat 8 OLI Collection 2 Level-1 (USGS), s3://usgs-landsat (requester pays)"
PAN_GAMMA = 1.5


def fetch_l2(grid: web.Grid, item_id: str) -> np.ndarray:
    """(7, h, w) raw values of vr.ASSETS on the grid (NaN = no data)."""
    params = {
        "collection": "landsat-c2-l2",
        "item": item_id,
        "assets": vr.ASSETS,
        "coord_crs": "EPSG:3857",
        "dst_crs": "EPSG:3857",
        "resampling": "nearest",
    }
    url = "{}/item/bbox/{:.4f},{:.4f},{:.4f},{:.4f}/{}x{}.tif".format(vr.DATA_API, *grid.bounds, grid.width, grid.height)
    r = remote.session().get(url, params=params, timeout=600)
    r.raise_for_status()
    with MemoryFile(r.content) as mf, mf.open() as ds:
        arr = ds.read().astype("float32")
    mask = arr[-1] == 0  # titiler's dataset mask
    return np.stack([np.where(mask | (b == 0), np.nan, b) for b in arr[: len(vr.ASSETS)]])


def main():
    sc = scene_mod.load()
    when = f"{sc['date']} {sc['time_utc']} UTC"
    print(f"scene {sc['id']} ({when})")

    # Level-2 bands
    grid = web.fine_grid(30.0)
    raw = fetch_l2(grid, sc["id"])
    bands = {a: (vr.celsius(v) if a == "lwir11" else vr.reflectance(v)) for a, v in zip(vr.ASSETS, raw)}
    sources = {"l2": web.write_cog(DATASET, np.stack(list(bands.values())), grid, list(bands), max_z_error=0.0005)}

    # Pan
    path = download.pan_path(sc)
    with rasterio.open(path) as ds:
        pan_dn, transform, crs, nodata = ds.read(1), ds.transform, ds.crs, ds.nodata
    pan_grid = web.fine_grid(15.0)
    pan = web.reproject(pan_dn, transform, crs, pan_grid, src_nodata=nodata)
    sources["pan"] = web.write_cog(f"{DATASET}-pan", pan, pan_grid, ["b8"], max_z_error=0.5)

    # Stretches over the extent
    products = {}
    for product, (title, assets) in vr.COMPOSITES.items():
        limits = [render.percentiles(bands[a], 1, 99) for a in assets]
        if product == "truecolor":  # one range for all three bands, to keep the color balance
            limits = [(min(l for l, _ in limits), max(h for _, h in limits))] * 3
        print(f"{product}: {[tuple(round(x, 3) for x in l) for l in limits]}")
        g = vr.GAMMA[product]
        combo = ", ".join(vr.BAND_LABEL[a] for a in assets)
        products[product] = web.product(
            title=title,
            subtitle=f"R, G, B = {combo}; surface reflectance\n{when}",
            native="30 m",
            source=vr.SOURCE,
            landmark_color="yellow" if product == "truecolor" else "white",
            layers=[web.layer("l2", web.rgb(*(web.channel(a, lo, hi, g) for a, (lo, hi) in zip(assets, limits))))],
        )
    lo, hi = render.percentiles(bands["lwir11"], 1, 99)
    norm = Normalize(math.floor(lo), math.ceil(hi))
    print(f"lst: {norm.vmin} to {norm.vmax} degC")
    products["lst"] = web.product(
        title="Landsat 8 land surface temperature",
        subtitle=f"TIRS B10 surface temperature (L2 ST_B10)\n{when}",
        native="100 m TIRS, resampled to 30 m by USGS",
        source=vr.SOURCE,
        landmark_color="cyan",
        layers=[web.layer("l2", web.colormap("inferno", norm, "Land surface temperature (°C)", band="lwir11", extend="both"))],
    )
    lo, hi = render.percentiles(pan, 1, 99.5)
    print(f"pan: DN {lo:.0f} to {hi:.0f}")
    products["pan"] = web.product(
        title="Landsat 8 panchromatic (OLI band 8)",
        subtitle=f"B8 pan, 0.50-0.68 µm; Level-1 {sc['l1_product_id']}\n{when}",
        native="15 m",
        source=L1_SOURCE,
        landmark_color="yellow",
        layers=[web.layer("pan", web.colormap("gray", Normalize(lo, hi), band="b8", gamma=PAN_GAMMA))],
    )
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
