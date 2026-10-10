# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "earthaccess"]
# ///
"""VIIRS Black Marble annual night lights (VNP46A4 v002, S-NPP), year 2025.

VNP46A4 is a 15 arc-second (~460 m) lat/lon product in 10x10 degree tiles
(h00 starts at 180 W, v00 at 90 N), so New Haven (72.9 W, 41.3 N) falls in
h10v04 (80-70 W, 40-50 N). Searches CMR with the padded view bounds, checks
that only h10v04 is returned, and downloads the HDF5 tile (~170 MB) to
data/viirs-nightlights/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import earthaccess

from common import config, views

DATASET = "viirs-nightlights"
SHORT_NAME = "VNP46A4"
YEAR = 2025  # most recent annual composite in the archive (as of 2026-10)
TILE = "h10v04"
PAD_M = 1000.0  # > 2 native pixels


def main():
    out_dir = config.data_dir(DATASET)
    earthaccess.login(strategy="netrc")
    granules = earthaccess.search_data(
        short_name=SHORT_NAME,
        version="2",
        temporal=(f"{YEAR}-01-01", f"{YEAR}-12-31"),
        bounding_box=views.all_bounds_lonlat(PAD_M),
    )
    # region cmr-temporal-quirk
    # The temporal search also returns the previous year (it ends on Jan 1);
    # select by file name, e.g. VNP46A4.A2025001.h10v04.002.<prod>.h5.
    links = [u for g in granules for u in g.data_links() if u.endswith(".h5")]
    print(f"{len(links)} granules: {[u.rsplit('/', 1)[1] for u in links]}")
    links = [u for u in links if f".A{YEAR}001." in u]
    if len(links) != 1 or f".{TILE}." not in links[0]:
        raise RuntimeError(f"expected one {YEAR} {TILE} granule, got {links}")
    # endregion cmr-temporal-quirk
    path = out_dir / links[0].rsplit("/", 1)[1]
    if not path.exists():
        earthaccess.download(links, str(out_dir))
    print(f"  {path.relative_to(config.REPO)} ({path.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
