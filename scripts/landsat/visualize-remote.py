# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Landsat 8 OLI/TIRS Collection 2 Level-2 band composites and land surface
temperature, fetched as raw values from the Microsoft Planetary Computer data
API (titiler) directly on each view's EPSG:3857 grid with nearest-neighbor
resampling, then stretched locally (same stretch in both views).

Scene: data/landsat/scene.json (from select_scene.py).
Products: truecolor, cir, veg, urban (surface reflectance), lst (ST_B10, deg C).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import requests
from matplotlib.colors import Normalize
from rasterio.io import MemoryFile

import scene as scene_mod
from common import remote, render
from common.views import VIEWS

DATASET = scene_mod.DATASET
DATA_API = "https://planetarycomputer.microsoft.com/api/data/v1"
SOURCE = "Landsat 8 OLI/TIRS Collection 2 Level-2 (USGS), via Microsoft Planetary Computer data API"

# Collection 2 Level-2 scale factors
SR_SCALE, SR_OFFSET = 2.75e-5, -0.2
ST_SCALE, ST_OFFSET = 0.00341802, 149.0  # kelvin

ASSETS = ["red", "green", "blue", "nir08", "swir16", "swir22", "lwir11"]
BAND_LABEL = {
    "red": "Red (B4)",
    "green": "Green (B3)",
    "blue": "Blue (B2)",
    "nir08": "NIR (B5)",
    "swir16": "SWIR1 (B6)",
    "swir22": "SWIR2 (B7)",
}
COMPOSITES = {
    # product: (title, assets as R, G, B)
    "truecolor": ("Landsat 8 true color", ("red", "green", "blue")),
    "cir": ("Landsat 8 color infrared", ("nir08", "red", "green")),
    "veg": ("Landsat 8 false color (vegetation)", ("swir16", "nir08", "red")),
    "urban": ("Landsat 8 false color (urban)", ("swir22", "swir16", "red")),
}
GAMMA = {"truecolor": 1.6, "cir": 1.2, "veg": 1.2, "urban": 1.2}


def fetch_bands(view, item_id: str, max_size: int = 1920) -> dict[str, np.ndarray]:
    """Raw uint16 values of ASSETS on the view grid (float32, NaN = nodata).

    The view is requested in chunks (full-view 7-band GeoTIFFs are >100 MB
    and the connection tends to drop).
    """
    sess = remote.session()
    params = {
        "collection": "landsat-c2-l2",
        "item": item_id,
        "assets": ASSETS,
        "coord_crs": "EPSG:3857",
        "dst_crs": "EPSG:3857",
        "resampling": "nearest",
    }

    def fetch(h, w, b):
        url = "{}/item/bbox/{:.4f},{:.4f},{:.4f},{:.4f}/{}x{}.tif".format(DATA_API, *b, w, h)
        for attempt in range(4):
            try:
                r = sess.get(url, params=params, timeout=600)
                r.raise_for_status()
                break
            except requests.exceptions.ChunkedEncodingError:
                if attempt == 3:
                    raise
        with MemoryFile(r.content) as mf, mf.open() as ds:
            return ds.read()

    arr = remote._fetch_chunks(view, max_size, 4, fetch).astype("float32")
    mask = arr[-1] == 0  # last band is titiler's dataset mask
    return {
        name: np.where(mask | (band == 0), np.nan, band) for name, band in zip(ASSETS, arr[: len(ASSETS)])
    }


def reflectance(dn):
    return dn * SR_SCALE + SR_OFFSET


def celsius(dn):
    return dn * ST_SCALE + ST_OFFSET - 273.15


def main():
    sc = scene_mod.load()
    when = f"{sc['date']} {sc['time_utc']} UTC"
    print(f"scene {sc['id']} ({when})")
    data = {}
    for view in VIEWS.values():
        print(view.title)
        data[view.name] = fetch_bands(view, sc["id"])

    # Stretch limits from the greater view (which contains the central one),
    # applied to both views.
    g = data["greater"]
    limits = {}
    for product, (_, bands) in COMPOSITES.items():
        limits[product] = [render.percentiles(reflectance(g[b]), 1, 99) for b in bands]
    # True color: one common range for all three bands, to keep the color balance.
    tc = limits["truecolor"]
    limits["truecolor"] = [(min(l for l, _ in tc), max(h for _, h in tc))] * 3
    lst_range = render.percentiles(celsius(g["lwir11"]), 1, 99)
    lst_range = (np.floor(lst_range[0]), np.ceil(lst_range[1]))
    print("stretch limits:", {k: [tuple(round(x, 3) for x in l) for l in v] for k, v in limits.items()})
    print(f"LST range {lst_range} deg C")

    for view in VIEWS.values():
        print(view.title)
        d = data[view.name]
        for product, (title, bands) in COMPOSITES.items():
            rgb = np.stack(
                [render.stretch(reflectance(d[b]), lo, hi, GAMMA[product]) for b, (lo, hi) in zip(bands, limits[product])]
            )
            combo = ", ".join(BAND_LABEL[b] for b in bands)
            render.save_figures(
                render.to_rgba(rgb), view, DATASET, product,
                title=title,
                subtitle=f"R, G, B = {combo}; surface reflectance\n{when}; 30 m pixels",
                source=SOURCE,
                landmark_color="yellow" if product == "truecolor" else "white",
            )  # fmt: skip

        norm = Normalize(*lst_range)
        lst = celsius(d["lwir11"])
        render.save_figures(
            render.colorize(lst, "inferno", norm=norm), view, DATASET, "lst",
            title="Landsat 8 land surface temperature",
            subtitle=f"TIRS B10 surface temperature (L2 ST_B10)\n{when}; 100 m TIRS, resampled to 30 m by USGS",
            colorbar=dict(cmap="inferno", norm=norm, label="Land surface temperature (°C)", extend="both"),
            source=SOURCE,
            landmark_color="cyan",
        )  # fmt: skip


if __name__ == "__main__":
    main()
