"""The NISAR L2 GCOV granule shared by the nisar-gcov scripts
(data/nisar-gcov/granule.json, written by select_granule.py), and a client for
raw covariance values from titiler-cmr.

titiler-cmr (Development Seed / NASA VEDA) opens the GCOV HDF5 granules on
the fly with its xarray backend. Requests are restricted to the one selected
granule with `granule_ur`, so nothing is mosaicked across dates or frames.
"""

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from rasterio.io import MemoryFile

from common import config, remote

DATASET = "nisar-gcov"
GRANULE_JSON = config.DATA / DATASET / "granule.json"

# region titiler-cmr-params
TITILER_CMR = "https://openveda.cloud/api/titiler-cmr"  # production; same app/version as staging
COLLECTION_CONCEPT_ID = "C2854338529-ASF"  # NISAR Provisional L2 GCOV
SHORT_NAME = "NISAR_L2_GCOV_PROVISIONAL_V1"
GROUP = "/science/LSAR/GCOV/grids/frequencyA"  # finest grid (frequency B is coarser)
VARIABLES = ["HHHH", "HVHV"]

# titiler-cmr runs on AWS Lambda, whose responses are capped at 6 MB:
# 640 x 640 px x 2 float32 bands = 3.3 MB per request.
MAX_CHUNK_PX = 640
# endregion titiler-cmr-params


def load() -> dict:
    if not GRANULE_JSON.exists():
        raise SystemExit(f"{GRANULE_JSON} missing; run scripts/{DATASET}/select_granule.py first")
    return json.loads(GRANULE_JSON.read_text())


# region native-grid-snapping
def snap_bounds(bounds, posting: float, origin=(0.0, 0.0)):
    """Expand (xmin, ymin, xmax, ymax) outward onto the native pixel-edge grid."""
    x0, y0 = origin
    xmin = x0 + math.floor((bounds[0] - x0) / posting) * posting
    ymin = y0 + math.floor((bounds[1] - y0) / posting) * posting
    xmax = x0 + math.ceil((bounds[2] - x0) / posting) * posting
    ymax = y0 + math.ceil((bounds[3] - y0) / posting) * posting
    return xmin, ymin, xmax, ymax
# endregion native-grid-snapping


# region fetch-covariance
def fetch_covariance(granule_ur: str, bounds, crs: str, pixel_m: float, workers: int = 4, sess=None) -> np.ndarray:
    """Raw HHHH and HVHV (linear power) for `bounds` in `crs`, at `pixel_m` pixels.

    With `crs` = the granule's native UTM CRS, `pixel_m` = its posting and
    `bounds` on its pixel-edge grid (see snap_bounds), the result is exactly
    the native grid (checked against the HDF5 file). Returns (2, rows, cols)
    float32 with NaN for nodata; the grid's upper-left corner is
    (bounds[0], bounds[3]).
    """
    sess = sess or remote.session()
    xmin, ymin, xmax, ymax = bounds
    width = round((xmax - xmin) / pixel_m)
    height = round((ymax - ymin) / pixel_m)
    params = {
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "granule_ur": granule_ur,
        "variables": VARIABLES,
        "group": GROUP,
        "coord_crs": crs,
        "dst_crs": crs,
        "reproject": "nearest",
        "return_mask": "false",
    }
    chunks = []
    for r0 in range(0, height, MAX_CHUNK_PX):
        for c0 in range(0, width, MAX_CHUNK_PX):
            h, w = min(MAX_CHUNK_PX, height - r0), min(MAX_CHUNK_PX, width - c0)
            b = (xmin + c0 * pixel_m, ymax - (r0 + h) * pixel_m, xmin + (c0 + w) * pixel_m, ymax - r0 * pixel_m)
            chunks.append((r0, c0, h, w, b))

    def get(chunk):
        r0, c0, h, w, b = chunk
        url = "{}/xarray/bbox/{:.3f},{:.3f},{:.3f},{:.3f}/{}x{}.tif".format(TITILER_CMR, *b, w, h)
        r = sess.get(url, params=params, timeout=600)
        r.raise_for_status()
        with MemoryFile(r.content) as mf, mf.open() as ds:
            arr = ds.read().astype("float32")
        if arr.shape != (len(VARIABLES), h, w):
            raise RuntimeError(f"titiler-cmr returned {arr.shape}, expected {(len(VARIABLES), h, w)}")
        return arr

    out = np.full((len(VARIABLES), height, width), np.nan, dtype="float32")
    with ThreadPoolExecutor(workers) as pool:
        for (r0, c0, h, w, _), arr in zip(chunks, pool.map(get, chunks)):
            out[:, r0 : r0 + h, c0 : c0 + w] = arr
    print(f"  fetched {width}x{height} px at {pixel_m:g} m in {len(chunks)} chunks")
    return np.where(out > 0, out, np.nan)  # log10 needs positive power; 0 / NaN = no data
# endregion fetch-covariance
