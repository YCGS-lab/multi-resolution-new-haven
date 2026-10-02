# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "h5py"]
# ///
"""VIIRS Black Marble annual night lights (VNP46A4, 2025), tile h10v04.

Product `radiance`: NearNadir_Composite_Snow_Free, the annual composite of
lunar-BRDF-corrected night-time DNB radiance from near-nadir views (view
zenith 0-20 deg) in the snow-free part of the year, on a log color scale.

Grid: geographic (WGS84 lat/lon), 15 arc-second pixels (1/240 deg; about
350 m E-W x 460 m N-S at New Haven), 2400 x 2400 per 10 x 10 deg tile. The
affine transform is built from the HDF-EOS StructMetadata upper-left corner
(80 W, 50 N); the file's `lat`/`lon` arrays (50.0 ... 40.004, -80.0 ...
-70.004) are the pixel upper-left corners and are checked against it.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h5py
import numpy as np
from matplotlib.colors import LogNorm
from rasterio.transform import from_origin, rowcol
from rasterio.windows import Window
from rasterio.windows import transform as window_transform

from common import config, render, views
from common.views import VIEWS

DATASET = "viirs-nightlights"
FILE_GLOB = "VNP46A4.A2025001.h10v04.002.*.h5"
GRID = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d"
FIELD = "NearNadir_Composite_Snow_Free"
FILL = -999.9
RES = 1 / 240  # 15 arc-seconds
PAD_M = 1000.0  # > 2 native pixels
NORM = LogNorm(vmin=0.5, vmax=200.0)  # nW cm-2 sr-1, same for both views
CMAP = "magma"
SOURCE = "NASA Black Marble VNP46A4 v002 (S-NPP VIIRS DNB), LAADS DAAC"


def tile_transform(f: h5py.File):
    """Affine transform from StructMetadata (UL corner, packed DMS degrees * 1e6)."""
    meta = f["HDFEOS INFORMATION/StructMetadata.0"][()].decode()
    ul = re.search(r"UpperLeftPointMtrs=\(([-\d.]+),([-\d.]+)\)", meta)
    nx = int(re.search(r"XDim=(\d+)", meta).group(1))
    west, north = float(ul.group(1)) / 1e6, float(ul.group(2)) / 1e6  # whole degrees here
    transform = from_origin(west, north, RES, RES)
    # Check against the coordinate arrays (pixel upper-left corners) and tile bounds.
    lat = f[f"{GRID}/Data Fields/lat"][:]
    lon = f[f"{GRID}/Data Fields/lon"][:]
    assert nx == lon.size == 2400
    assert np.allclose(lon, west + RES * np.arange(nx), atol=1e-6), "lon array mismatch"
    assert np.allclose(lat, north - RES * np.arange(lat.size), atol=1e-6), "lat array mismatch"
    assert np.isclose(west + nx * RES, f.attrs["EastBoundingCoord"]), "east bound mismatch"
    return transform


def read_subset(path: Path):
    """Radiance (NaN = fill) for a window covering all views, and its transform."""
    with h5py.File(path) as f:
        transform = tile_transform(f)
        w, s, e, n = views.all_bounds_lonlat(PAD_M)
        rows, cols = rowcol(transform, [w, e], [n, s], op=np.floor)
        (r0, r1), (c0, c1) = map(int, rows), map(int, cols)
        win = Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        ds = f[f"{GRID}/Data Fields/{FIELD}"]
        arr = ds[r0 : r1 + 1, c0 : c1 + 1].astype("float32")
        quality = f[f"{GRID}/Data Fields/{FIELD}_Quality"][r0 : r1 + 1, c0 : c1 + 1]
        num = f[f"{GRID}/Data Fields/{FIELD}_Num"][r0 : r1 + 1, c0 : c1 + 1]
        attrs = {k: f.attrs[k] for k in ("RangeBeginningDate", "RangeEndingDate", "PlatformShortName")}
    arr = np.where((arr == np.float32(FILL)) | (quality == 255), np.nan, arr)
    print(f"  window rows {r0}-{r1}, cols {c0}-{c1} ({arr.shape[0]}x{arr.shape[1]} px)")
    print(f"  radiance {np.nanmin(arr):.2f} to {np.nanmax(arr):.1f} nW/cm2/sr; quality {np.unique(quality)}; "
          f"obs/pixel {num.min()}-{num.max()} (median {np.median(num):.0f})")  # fmt: skip
    return arr, window_transform(win, transform), attrs


def main():
    paths = sorted(config.data_dir(DATASET).glob(FILE_GLOB))
    if not paths:
        sys.exit(f"no {FILE_GLOB} in data/{DATASET}/ - run download.py first")
    path = paths[-1]
    print(path.name)
    rad, transform, attrs = read_subset(path)
    start, end = (a.decode() for a in (attrs["RangeBeginningDate"], attrs["RangeEndingDate"]))
    # Clip low values (incl. 0 over water) to the bottom of the log scale.
    rad = np.where(np.isfinite(rad), np.maximum(rad, NORM.vmin), np.nan)

    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(rad, transform, "EPSG:4326", view)
        print(f"  in view: {np.nanmin(grid):.2f} to {np.nanmax(grid):.1f} nW/cm2/sr")
        img = render.colorize(grid, CMAP, norm=NORM)
        render.save_figures(
            img, view, DATASET, "radiance",
            title="VIIRS Black Marble night lights",
            subtitle=(
                f"VNP46A4 annual composite {start[:4]} ({start} to {end}), near-nadir, snow-free; "
                "15 arc-second (~350 x 460 m) pixels"
            ),
            colorbar=dict(cmap=CMAP, norm=NORM, label="Radiance (nW cm$^{-2}$ sr$^{-1}$)", extend="min"),
            source=SOURCE,
            landmark_color="cyan",
        )  # fmt: skip


if __name__ == "__main__":
    main()
