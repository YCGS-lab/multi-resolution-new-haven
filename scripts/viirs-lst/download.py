# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "earthaccess"]
# ///
"""VIIRS 750 m land surface temperature swath: one S-NPP daytime granule.

Product: VNP21 v002, "VIIRS/NPP Land Surface Temperature and Emissivity 6-Min
L2 Swath 750m V002" (LP DAAC, CMR C2545314550-LPCLOUD). The standard
(science-quality) LST product, TES algorithm on the M14-M16 bands. The file
carries per-pixel latitude/longitude (M-band geolocation, as in VNP03MOD)
and the sensor zenith angle, so no separate geolocation granule is needed.

Selected granule: VNP21.A2026154.1748.002 = 2026-06-03 17:48-17:54 UTC;
New Haven is scanned at ~17:52:40 UTC (13:52 EDT).

How it was chosen (summer 2026, Jun-Aug, daytime, S-NPP / NOAA-20 / NOAA-21):
1. All 417 daytime VNP21/VJ121/VJ221 granules intersecting New Haven were
   screened by view angle, estimated from the cross-track distance of New
   Haven to the granule centerline (CMR footprint polygons): 35 granules are
   within ~7 deg of nadir.
2. Those were ranked by cloudiness over the greater view in the GIBS VIIRS
   corrected-reflectance true color of each satellite/day; 6 near-nadir
   scenes were completely clear (2026-06-03 S-NPP, 06-04 N20, 06-08 S-NPP,
   07-01 N20, 07-17 N20, 07-25 N21).
3. Those 6 were downloaded and scored on the LST QC over the views: all have
   LST for 100% of land pixels with 87-93% "best quality" mandatory QA (the
   rest "nominal", flagged as near cloud) and 100% best quality over the
   central view. 2026-06-03 S-NPP was picked as the closest to nadir (sensor
   zenith 2.5-4 deg over the greater view, so pixels are ~750 m and nearly
   square), as it is the S-NPP VNP21 product itself, with a median LST error
   estimate of 0.96 K, and because the GOES-19 LST at the nearest hour
   (18:01 UTC) is also cloud-free and high quality (scripts/goes-lst/).
   Runners-up: VJ221 2026-07-25 17:42 (4-6 deg, 93% best QA) and VJ121
   2026-07-17 17:42 (3-4.5 deg, 88%).

The 6-min swath file (~83 MB) is downloaded whole to data/viirs-lst/; the
LP DAAC cloud archive offers no spatial subsetting for this L2 swath.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import earthaccess

from common import config, views

DATASET = "viirs-lst"
SHORT_NAME, VERSION = "VNP21", "002"
GRANULE = "VNP21.A2026154.1748.002"  # file name prefix (+ production time)
TEMPORAL = ("2026-06-03T17:48:00Z", "2026-06-03T17:53:59Z")


def main():
    out_dir = config.data_dir(DATASET)
    existing = sorted(out_dir.glob(f"{GRANULE}.*.nc"))
    if existing:
        print(f"  already have {existing[-1].relative_to(config.REPO)}")
        return
    earthaccess.login(strategy="netrc")
    granules = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=TEMPORAL,
        bounding_box=views.all_bounds_lonlat(1500.0),
    )
    links = [u for g in granules for u in g.data_links() if u.rsplit("/", 1)[1].startswith(GRANULE) and u.endswith(".nc")]
    if not links:
        sys.exit(f"{GRANULE} not found in CMR")
    print(f"  downloading {links[0].rsplit('/', 1)[1]}")
    paths = earthaccess.download(links[:1], str(out_dir))
    print(f"  {Path(paths[0]).relative_to(config.REPO)}")


if __name__ == "__main__":
    main()
