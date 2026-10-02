# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""GOES-19 (GOES-East) ABI L2 land surface temperature, CONUS sector, 2 km.

Product: ABI-L2-LSTC ("ABI L2 Land Surface (Skin) Temperature", CONUS, 2 km
at nadir, hourly), from the public NOAA Open Data bucket s3://noaa-goes19
(anonymous HTTPS). One granule, ~2.9 MB:

    OR_ABI-L2-LSTC-M6_G19_s20261541801179_e20261541803552_c20261541807089.nc
    scan 2026-06-03 18:01:18-18:03:55 UTC (14:01 EDT)

Why this product: the GOES-R LST products are
  - ABI-L2-LSTC    CONUS, 2 km, hourly (scan ~HH:01-HH:04)
  - ABI-L2-LST2KMF full disk at 2 km, hourly (same 2 km fixed grid, 10-min
                   full-disk scan; values over New Haven differ from LSTC
                   by up to ~1 K as it is a different scan), ~11 MB
  - ABI-L2-LSTF    full disk at 10 km
  - ABI-L2-LSTM    mesoscale sectors, 2 km; the sectors (M1/M2) were over
                   the central US, not Connecticut, at this hour
LSTC and LST2KMF are both the finest (2 km) resolution; LSTC is used for its
short, well-defined scan time and small file.

Why this hour: it is the hourly LST closest to the VIIRS VNP21 overpass used
for scripts/viirs-lst (2026-06-03 ~17:52 UTC), 9 minutes later, so the two
are directly comparable. All land pixels over the greater view are
high-quality (DQF 0) and cloud-free at 18:01 (the 17:01 scan had some
cloud and low-quality (DQF 2) retrievals along the coast).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests

from common import config

DATASET = "goes-lst"
BUCKET = "https://noaa-goes19.s3.amazonaws.com"
KEYS = ["ABI-L2-LSTC/2026/154/18/OR_ABI-L2-LSTC-M6_G19_s20261541801179_e20261541803552_c20261541807089.nc"]


def main():
    out_dir = config.data_dir(DATASET)
    for key in KEYS:
        out = out_dir / key.rsplit("/", 1)[1]
        if out.exists():
            print(f"  already have {out.relative_to(config.REPO)}")
            continue
        print(f"  downloading {key}")
        r = requests.get(f"{BUCKET}/{key}", timeout=120)
        r.raise_for_status()
        out.write_bytes(r.content)
        print(f"  {out.relative_to(config.REPO)} ({len(r.content) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
