"""Derive one function's package from a variant's zip by leaving out distributions (V5, V6).

    python fn_package.py IN.zip OUT.zip --function noaa-raster
    python fn_package.py IN.zip OUT.zip --drop pkg ...

Distributions are removed with everything their RECORD lists (including the
auditwheel .libs directory of their bundled libraries). The function's
YCGS_BACKENDS keeps the app from importing them; optional imports elsewhere
(rio_tiler.io tries `import xarray`) just find them missing.
"""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

EPOCH = (1980, 1, 1, 0, 0, 0)
XARRAY_STACK = ["xarray", "pandas", "python-dateutil", "tzdata", "six", "dask", "cloudpickle", "toolz", "partd",
                "locket", "fsspec", "rioxarray", "zarr", "numcodecs", "donfig", "google-crc32c", "crc32c", "msgspec",
                "obstore", "obspec", "obspec-utils", "h5netcdf", "h5py"]
CMR = ["titiler-cmr", "titiler-mosaic", "pillow", "shapely", "psutil", "isodate"]

# What each function can do without (from bench/trace.py per function, then checked in a Lambda container).
FUNCTIONS = {
    # V6: one function per deployment and reader type
    "nasa-raster": ["h5netcdf"],
    "nasa-xarray": [],
    "noaa-raster": XARRAY_STACK + CMR,
    "noaa-xarray": ["pillow"],
    "ecmwf-xarray": ["h5netcdf", "h5py", "pillow"],
    # V5: one package per deployment
    "nasa": [],
    "noaa": ["pillow"],
    "ecmwf": ["h5netcdf", "h5py", "pillow"],
}
# YCGS_BACKENDS of each function
BACKENDS = {
    "nasa-raster": "cmr-rasterio", "nasa-xarray": "cmr-xarray,cmr-xarray-grouped",
    "noaa-raster": "cog", "noaa-xarray": "xarray", "ecmwf-xarray": "xarray",
    "nasa": "cmr-xarray,cmr-xarray-grouped,cmr-rasterio", "noaa": "xarray,cog", "ecmwf": "xarray",
}


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "_", n).lower()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--function", choices=sorted(FUNCTIONS))
    ap.add_argument("--drop", nargs="*", default=[])
    args = ap.parse_args()
    drop = {norm(d) for d in args.drop + (FUNCTIONS[args.function] if args.function else [])}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(args.src) as z:
            z.extractall(root)
            modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        removed = 0
        for info in root.glob("*.dist-info"):
            if norm(info.name.split("-")[0]) not in drop:
                continue
            lines = (info / "RECORD").read_text().splitlines() if (info / "RECORD").exists() else []
            # File by file: distributions share namespace directories (titiler-cmr and titiler-core
            # both install under titiler/). Sources were compiled to .pyc next to them (slim.py).
            for ln in lines:
                rel = ln.split(",")[0]
                for p in (root / rel, root / (rel[:-3] + ".pyc") if rel.endswith(".py") else None):
                    if p is not None and p.is_file():
                        removed += p.stat().st_size
                        p.unlink()
            shutil.rmtree(info, ignore_errors=True)
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
        files = sorted(p for p in root.rglob("*") if p.is_file())
        with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in files:
                name = str(p.relative_to(root))
                info = zipfile.ZipInfo(name, EPOCH)
                info.external_attr = (modes.get(name) or 0o644) << 16
                info.compress_type = zipfile.ZIP_STORED if name.endswith(".zst") else zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes(), compresslevel=9)
        size = sum(p.stat().st_size for p in files)
    print(f"{args.out.name}: {size / 2**20:.1f} MB unzipped (removed {removed / 2**20:.1f} MB), "
          f"{args.out.stat().st_size / 2**20:.1f} MB zipped")


if __name__ == "__main__":
    main()
