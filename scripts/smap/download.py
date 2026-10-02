# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "earthaccess", "h5py"]
# ///
"""Download SMAP L4 root-zone soil moisture (SPL4SMGP v008) around New Haven.

One 3-hourly "geophysical" granule: 2026-07-30 15:00-18:00 UTC (11:00-14:00
EDT), the day after the 2026-07-29 storm shown in the CHIRPS figures (~40 mm
at New Haven), so the soil should be near its wettest for the summer.
v008 is the latest SPL4SMGP version in CMR (v007 ended 2025-07).

Instead of downloading the whole ~145 MB HDF5 file, the granule is opened
over HTTPS with earthaccess and only `Geophysical_Data/sm_rootzone` and the
x/y coordinate vectors are read (sm_rootzone is stored as a single gzip
chunk, so the full global field is transferred once, ~tens of MB). The
pixels covering all views (padded by 2 cells) are written to
data/smap/<granule>.sm_rootzone.newhaven.tif in EPSG:6933.

Grid: EASE-Grid 2.0 global 9 km, 3856 x 1624 cells of 9008.055210146 m,
upper-left corner (-17367530.445, 7314540.831). This is checked against the
file's x/y cell-center coordinates below.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from common import config, views
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds

DATASET = "smap"
SHORT_NAME, VERSION = "SPL4SMGP", "008"
TEMPORAL = ("2026-07-30T16:00:00Z", "2026-07-30T17:00:00Z")  # selects the 15:00-18:00 UTC granule
VARIABLE = "Geophysical_Data/sm_rootzone"
CRS = "EPSG:6933"
CELL = 9008.055210146
NCOLS, NROWS = 3856, 1624
TRANSFORM = Affine(CELL, 0, -NCOLS / 2 * CELL, 0, -CELL, NROWS / 2 * CELL)
FILL = -9999.0


def output_path() -> Path:
    matches = sorted(config.data_dir(DATASET).glob("SMAP_L4_SM_gph_*.sm_rootzone.newhaven.tif"))
    if not matches:
        raise FileNotFoundError("run scripts/smap/download.py first")
    return matches[-1]


def main():
    import earthaccess  # imported here so visualize.py can import this module without it
    import h5py

    earthaccess.login(strategy="netrc")
    granules = earthaccess.search_data(short_name=SHORT_NAME, version=VERSION, temporal=TEMPORAL)
    assert len(granules) == 1, [g["umm"]["GranuleUR"] for g in granules]
    g = granules[0]
    name = Path(g.data_links()[0]).name
    t = g["umm"]["TemporalExtent"]["RangeDateTime"]
    print(f"{name}: {t['BeginningDateTime']} to {t['EndingDateTime']}")

    with h5py.File(earthaccess.open([g])[0], "r") as h:
        x, y = h["x"][:], h["y"][:]
        # The stored cell centers are float32-rounded; they must agree with the
        # nominal grid to well under a cell.
        cx = TRANSFORM.c + CELL * (np.arange(NCOLS) + 0.5)
        cy = TRANSFORM.f - CELL * (np.arange(NROWS) + 0.5)
        dx, dy = np.abs(x - cx).max(), np.abs(y - cy).max()
        print(f"  grid check: max |x - nominal| {dx:.2f} m, |y - nominal| {dy:.2f} m")
        assert x.shape == (NCOLS,) and y.shape == (NROWS,) and dx < 10 and dy < 10

        win = from_bounds(*views.all_bounds_in(CRS, pad_m=2 * CELL), transform=TRANSFORM)
        col0, row0 = int(np.floor(win.col_off)), int(np.floor(win.row_off))
        col1, row1 = int(np.ceil(win.col_off + win.width)), int(np.ceil(win.row_off + win.height))
        win = Window(col0, row0, col1 - col0, row1 - row0)
        ds = h[VARIABLE]
        sm = ds[win.row_off : win.row_off + win.height, win.col_off : win.col_off + win.width].astype("float32")
        units = ds.attrs["units"].decode()
    sm[sm == FILL] = np.nan

    out = config.data_dir(DATASET) / f"{Path(name).stem}.sm_rootzone.newhaven.tif"
    profile = dict(
        driver="GTiff", dtype="float32", width=sm.shape[1], height=sm.shape[0], count=1,
        crs=CRS, transform=rasterio.windows.transform(win, TRANSFORM), nodata=np.nan,
    )  # fmt: skip
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(sm, 1)
        dst.update_tags(
            granule=name,
            variable=VARIABLE,
            units=units,
            time_begin=t["BeginningDateTime"],
            time_end=t["EndingDateTime"],
            window=f"rows {win.row_off}-{win.row_off + win.height - 1}, cols {win.col_off}-{win.col_off + win.width - 1}",
        )
    print(f"  wrote {out.relative_to(config.REPO)} {sm.shape}, {np.isnan(sm).sum()} fill cells")
    print(np.array2string(sm, precision=3))


if __name__ == "__main__":
    main()
