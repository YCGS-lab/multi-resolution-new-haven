# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""PRISM 800 m (30 arc-second) monthly mean air temperature (tmean), July 2026.

Downloads the CONUS grid (~50 MB zip, a Cloud-Optimized GeoTIFF in NAD83
geographic coordinates) from the PRISM web service, and keeps only a small
window around the views (padded by several native pixels) plus the PRISM
metadata files, in data/prism/.

Web service docs: https://prism.oregonstate.edu/documents/PRISM_downloads_web_service.pdf
Note: the service allows each file to be downloaded only twice per day per IP,
so this script skips the download when the clipped file already exists, and
`--zip PATH` uses an already-downloaded zip instead.
"""

import argparse
import math
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rasterio
import requests
from rasterio.windows import Window, from_bounds

from common import config, views

DATASET = "prism"
VAR, MONTH = "tmean", "202607"
URL = f"https://services.nacse.org/prism/data/get/us/800m/{VAR}/{MONTH}"
STEM = f"prism_{VAR}_us_30s_{MONTH}"
PAD_M = 4000  # ~5 native pixels


def download(zpath: Path):
    print(f"downloading {URL} ...")
    with requests.get(URL, stream=True, timeout=600) as r:
        r.raise_for_status()
        if "zip" not in r.headers.get("Content-Type", ""):
            raise RuntimeError(f"unexpected response: {r.headers.get('Content-Type')}: {r.text[:500]}")
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, help=f"use this already-downloaded {STEM}.zip")
    args = parser.parse_args()
    out_dir = config.data_dir(DATASET)
    out = out_dir / f"{STEM}_newhaven.tif"
    if out.exists():
        print(f"{out.relative_to(config.REPO)} exists; skipping download")
        return
    with tempfile.TemporaryDirectory() as tmp:
        zpath = args.zip or Path(tmp) / f"{STEM}.zip"
        if not args.zip:
            download(zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
            for name in z.namelist():  # keep the small metadata files
                if not name.endswith((".tif", ".aux.xml")):
                    (out_dir / name).write_bytes((Path(tmp) / name).read_bytes())
        with rasterio.open(Path(tmp) / f"{STEM}.tif") as src:
            west, south, east, north = views.all_bounds_in(src.crs, PAD_M)
            w = from_bounds(west, south, east, north, src.transform)
            c0, r0 = math.floor(w.col_off), math.floor(w.row_off)
            win = Window(c0, r0, math.ceil(w.col_off + w.width) - c0, math.ceil(w.row_off + w.height) - r0)
            data = src.read(1, window=win)
            profile = src.profile | dict(
                width=win.width,
                height=win.height,
                transform=src.window_transform(win),
                tiled=False,
                blockxsize=None,
                blockysize=None,
            )
            profile = {k: v for k, v in profile.items() if v is not None}
            with rasterio.open(out, "w", **profile) as dst:
                dst.write(data, 1)
    print(f"wrote {out.relative_to(config.REPO)} ({win.width}x{win.height} px)")


if __name__ == "__main__":
    main()
