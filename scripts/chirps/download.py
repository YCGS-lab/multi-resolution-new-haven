# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Download one day of CHIRPS v3.0 daily precipitation around New Haven.

Windowed read of the final, IMERG-disaggregated ("sat") daily COG over HTTP:
only the 0.05-degree pixels covering all views (padded by 2 pixels) are
fetched and saved to data/chirps/chirps-v3.0.sat.<date>.newhaven.tif.

Date: 2026-07-29. A scan of Jan-Sep 2026 (find_rainy_days.py) shows it is
one of the wettest days of 2026 at New Haven (~40 mm at the Green) and, among
the very wet days, the one with the clearest spatial pattern across the
greater view (~50 mm in the west to ~30 mm in the east, rather than
pixel-to-pixel noise). It is in the quality-controlled "final" stream.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chirps
import numpy as np
import rasterio
from common import config, views

DATASET = "chirps"
DATE = dt.date(2026, 7, 29)
PAD_M = 2 * chirps.RES * 111_000  # two native pixels


def output_path(date: dt.date = DATE) -> Path:
    return config.data_dir(DATASET) / f"chirps-v3.0.sat.{date:%Y.%m.%d}.newhaven.tif"


def main():
    src = chirps.url(DATE)
    bounds = views.all_bounds_lonlat(PAD_M)
    print(f"reading {src}\n  window {bounds}")
    arr, transform, tags = chirps.read_window(src, bounds)
    out = output_path()
    profile = dict(
        driver="GTiff", dtype="float32", width=arr.shape[1], height=arr.shape[0], count=1,
        crs="EPSG:4326", transform=transform, nodata=np.nan, compress="deflate",
    )  # fmt: skip
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.update_tags(
            source_url=src,
            date=DATE.isoformat(),
            units="mm/day",
            product="CHIRPS v3.0 daily final, IMERG Late V07 disaggregation (sat)",
            source_file_datetime=tags.get("TIFFTAG_DATETIME", ""),
        )
    print(f"  wrote {out.relative_to(config.REPO)} {arr.shape}, {np.nanmin(arr):.1f}-{np.nanmax(arr):.1f} mm/day")


if __name__ == "__main__":
    main()
