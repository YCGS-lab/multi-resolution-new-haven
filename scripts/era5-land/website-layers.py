# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for ERA5-Land 2 m air temperature, read live from ECMWF's
Analysis-Ready, Cloud-Optimised (ARCO) Zarr store of ERA5-Land, with the CDS
API key the user enters on the website (Credentials) as a bearer token.
Without a key the dataset is locked.

ECMWF publishes the store twice: geo-chunked (for long time series at a
point) and time-chunked (for large areas over short periods). The website
draws maps, so it reads the time-chunked store: the chunks of the selected
hour over the area in view only. Any hour from 1950 to about 5 days ago (the
store's time axis); the default is the latest hour.

Products: t2m.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.colors import Normalize

from common import web

DATASET = "era5-land"
CMAP = "RdYlBu_r"
SOURCE = "Copernicus Climate Change Service (C3S), ERA5-Land hourly (Muñoz Sabater 2019), ECMWF ARCO Zarr store"
# The time-chunked (map) store of the 2 m temperature group; the geo-chunked
# twin, .../cadl-arco-geo-007/.../geoChunked.zarr, is for point time series.
ARCO_TIME_CHUNKED = "https://arco.datastores.ecmwf.int/cadl-arco-time-007/arco/reanalysis_era5_land/sfc-2m-temperature/timeChunked.zarr"
T_RANGE = (-20.0, 40.0)  # deg C: one range for all seasons


def main():
    # region era5-live-source
    sources = {
        "t2m": web.arco_zarr_source(
            ARCO_TIME_CHUNKED, ["t2m", "2m_temperature"], "t2m", native_deg=0.1, credential="cds", offset=-273.15
        )
    }
    meta = dict(
        time=web.time_spec("hour", web.avail_zarr("t2m"), label="Time (UTC)", widget="calendar"),
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
