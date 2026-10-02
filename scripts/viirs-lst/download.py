# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "earthaccess"]
# ///
"""VIIRS 375 m land surface temperature swath: one NOAA-21 daytime granule.

Product: VJ221IMG_NRT v002 ("VIIRS/JPSS2 Land Surface Temperature and
Emissivity 6-Min L2 Swath 375m NRT", LANCE). There is no standard (non-NRT)
375 m LST collection in CMR (only VNP21IMG_NRT / VJ121IMG_NRT /
VJ221IMG_NRT), and LANCE keeps only a rolling ~7-day archive, so a summer
scene is not available; this granule was the best of 2026-09-25..10-02.

Selected granule: VJ221IMG_NRT.A2026275.1748 = 2026-10-02 17:48-17:54 UTC
(13:48 EDT). Why: the clearest day of the week over New Haven (GIBS true
color: the other days were overcast), and the only near-nadir overpass of
that day (view angle 5.5-7 deg over the view, so pixels are ~375 m; the
S-NPP 16:42 and NOAA-20 17:00 passes were at 54-68 deg and fully cloudy
over the view). Over the greater view ~55% of pixels have LST (cloud over
parts of the south and east, water not retrieved).

The 6-min swath file (~260 MB, includes per-pixel Latitude/Longitude) is
downloaded whole to data/viirs-lst/; LANCE offers no server-side subsetting.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import earthaccess

from common import config, views

DATASET = "viirs-lst"
SHORT_NAME = "VJ221IMG_NRT"
GRANULE = "VJ221IMG_NRT.A2026275.1748.002"  # file name prefix (+ production time)
TEMPORAL = ("2026-10-02T17:48:00Z", "2026-10-02T17:53:59Z")


def main():
    out_dir = config.data_dir(DATASET)
    existing = sorted(out_dir.glob(f"{GRANULE}.*.nc"))
    if existing:
        print(f"  already have {existing[-1].relative_to(config.REPO)}")
        return
    earthaccess.login(strategy="netrc")
    granules = earthaccess.search_data(
        short_name=SHORT_NAME, temporal=TEMPORAL, bounding_box=views.all_bounds_lonlat(1000.0)
    )
    links = [u for g in granules for u in g.data_links() if u.rsplit("/", 1)[1].startswith(GRANULE)]
    if not links:
        sys.exit(
            f"{GRANULE} not found in CMR: LANCE NRT data are only kept for ~7 days. "
            "Pick a newer granule (see the selection notes above)."
        )
    print(f"  downloading {links[0].rsplit('/', 1)[1]}")
    paths = earthaccess.download(links[:1], str(out_dir))
    print(f"  {Path(paths[0]).relative_to(config.REPO)}")


if __name__ == "__main__":
    main()
