# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "netcdf4"]
# ///
"""Website layers for GOES-19 ABI land surface temperature (ABI-L2-LSTC,
hourly, 2 km), read live from the NetCDF scans in the public NOAA Open Data
bucket by this repository's tiler (tiler/, preset `goes19-lst`; deployed next
to the bucket in AWS us-east-1, env.json `tiler`). Browsers cannot read the
NetCDF files directly, so the dataset is cloud-only; the pre-built scan
(create-cog.py, "goes-lst-prebuilt") still works locally.

Every hour since GOES-19 became GOES-East (2025-04-07) can be picked; the
tiler uses the scan nearest to the hour. LST exists for clear-sky land only,
so a cloudy hour shows little. Only high and medium quality retrievals
(DQF 0-1) are drawn, as in visualize.py.

Products: lst.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from matplotlib.colors import Normalize

from common import web
from visualize import CMAP, DATASET, LST_RANGE, SOURCE


def main():
    # region goes-lst-live-source
    sources = {
        "lst": web.tiler_source(
            "goes19-lst", ["LST", "DQF"], native_m=2500.0, derive={"lst": "DQF <= 1 ? LST - 273.15 : NaN"}
        )
    }
    meta = dict(
        time=web.time_spec("hour", web.avail_range("hour", "2025-04-07T15:00:00Z", latency_hours=1), label="Hour (UTC)", widget="calendar"),
        requires=web.requires_cloud("NOAA GOES NetCDF scans in AWS us-east-1, read by a tiler next to the data", "tiler"),
        coverage=web.coverage(-135.0, 15.0, -60.0, 55.0, "the GOES-East CONUS sector"),
        min_zoom=4,
    )
    # endregion goes-lst-live-source
    products = {
        "lst": web.product(
            title="GOES-19 ABI land surface temperature (2 km)",
            subtitle="Hourly CONUS scan nearest the hour (ABI-L2-LSTC); clear-sky land, high and medium quality (DQF 0-1)",
            native="2 km at nadir, ~2.5 × 3 km here",
            source=SOURCE,
            landmark_color="cyan",
            layers=[web.layer("lst", web.colormap(CMAP, Normalize(*LST_RANGE), "Land surface temperature (°C)", band="lst", extend="both"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
