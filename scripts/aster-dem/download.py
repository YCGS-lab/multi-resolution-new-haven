# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "earthaccess"]
# ///
"""ASTER Global DEM v3 (ASTGTM.003, 1 arc-second) tiles covering the views.

Searches CMR for ASTGTM v003 granules intersecting the padded view bounds
(N41W073 and N41W074 here: the greater view straddles 73 W) and downloads
only their `_dem.tif` files to data/aster-dem/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import earthaccess

from common import config, views

DATASET = "aster-dem"
PAD_M = 100.0  # > 3 native pixels


def main():
    out_dir = config.data_dir(DATASET)
    earthaccess.login(strategy="netrc")
    bbox = views.all_bounds_lonlat(PAD_M)
    granules = earthaccess.search_data(short_name="ASTGTM", version="003", bounding_box=bbox)
    print(f"{len(granules)} granules: {[g['umm']['GranuleUR'] for g in granules]}")
    links = [u for g in granules for u in g.data_links() if u.endswith("_dem.tif")]
    todo = [u for u in links if not (out_dir / u.rsplit("/", 1)[1]).exists()]
    if todo:
        earthaccess.download(todo, str(out_dir))
    for u in links:
        print(f"  {(out_dir / u.rsplit('/', 1)[1]).relative_to(config.REPO)}")


if __name__ == "__main__":
    main()
