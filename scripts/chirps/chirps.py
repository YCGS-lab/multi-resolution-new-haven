"""CHIRPS v3.0 daily file locations and windowed reads over HTTP.

Daily CHIRPS v3 is a pentad product disaggregated to days; the "sat" variant
uses NASA IMERG Late V07 daily ratios (the "rnl" variant uses ERA5). Final
daily files are published as COGs (512x512 tiles, LZW), so a small window
costs one or two HTTP range requests; preliminary daily files (the most recent
month or so) are strip GeoTIFFs, which GDAL can still read row by row.
"""

import datetime as dt

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds

BASE = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily"
RES = 0.05  # degrees; the files store 0.05000000074505806 (float32 round-off)
NODATA = -9999.0

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.cog",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
)


# region chirps-urls-and-window
def url(date: dt.date, stream: str = "final") -> str:
    """URL of the daily CHIRPS v3 (IMERG-disaggregated) file for `date`."""
    if stream == "final":
        return f"{BASE}/final/sat/cogs/{date.year}/chirps-v3.0.sat.{date:%Y.%m.%d}.cog"
    if stream == "prelim":
        return f"{BASE}/prelim/sat/{date.year}/chirps-v3.0.prelim.{date:%Y.%m.%d}.tif"
    raise ValueError(stream)


def read_window(src_url: str, bounds_lonlat) -> tuple[np.ndarray, Affine, dict]:
    """Read the pixels intersecting (west, south, east, north), snapped outward.

    Returns (float32 array with NaN for nodata, exact 0.05-degree transform,
    file tags). The transform is rebuilt from the nominal 0.05 degree grid
    (origin -180, 60), removing the float32 round-off stored in the files.
    """
    w, s, e, n = bounds_lonlat
    with rasterio.Env(**GDAL_ENV), rasterio.open("/vsicurl/" + src_url) as ds:
        win = from_bounds(w, s, e, n, transform=ds.transform)
        col0, row0 = int(np.floor(win.col_off)), int(np.floor(win.row_off))
        col1 = int(np.ceil(win.col_off + win.width))
        row1 = int(np.ceil(win.row_off + win.height))
        win = Window(col0, row0, col1 - col0, row1 - row0)
        arr = ds.read(1, window=win).astype("float32")
        tags = ds.tags()
    arr[arr <= NODATA] = np.nan
    transform = Affine(RES, 0, -180 + col0 * RES, 0, -RES, 60 - row0 * RES)
    return arr, transform, tags
# endregion chirps-urls-and-window
