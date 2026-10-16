# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for ERA5-Land 2 m air temperature, read live from the
Copernicus Climate Data Store: with the CDS API key the user enters on the
website (Credentials), the website requests the selected hour (or, for an
animation, all of its hours at once) over the area in view as GRIB, decodes
it and draws the 0.1 deg cells. Without a key the dataset is locked.

Any hour from 1950 to about a week ago (ERA5-Land's latency); the default is
the latest hour. CDS requests wait in a queue: from a few seconds to minutes.

Products: t2m.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.colors import Normalize

from common import web

DATASET = "era5-land"
CMAP = "RdYlBu_r"
SOURCE = "Copernicus Climate Change Service (C3S), ERA5-Land hourly (Muñoz Sabater 2019), via the Climate Data Store"
T_RANGE = (-20.0, 40.0)  # deg C: one range for all seasons


def main():
    # region era5-live-source
    sources = {"t2m": web.cds_source("reanalysis-era5-land", "2m_temperature", "t2m", native_deg=0.1, offset=-273.15)}
    meta = dict(
        time=web.time_spec("hour", web.avail_hourly("1950-01-01", lag_days=6), label="Time (UTC)", widget="calendar"),
        requires=web.requires_credential("cds"),
        min_zoom=5,
    )
    # endregion era5-live-source
    products = {
        "t2m": web.product(
            title="ERA5-Land 2 m air temperature",
            subtitle="Hourly reanalysis; land only (sea cells transparent)",
            native="0.1° grid (~8 km E-W × 11 km N-S at New Haven; native model ~9 km)",
            source=SOURCE,
            layers=[web.layer("t2m", web.colormap(CMAP, Normalize(*T_RANGE), "2 m air temperature (°C)", band="t2m", extend="both"))],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
