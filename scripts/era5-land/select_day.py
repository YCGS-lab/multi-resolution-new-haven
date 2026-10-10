# /// script
# requires-python = ">=3.11"
# dependencies = ["cdsapi>=0.7.2", "xarray", "netcdf4", "numpy", "pandas", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Pick a sunny summer 2026 day in New Haven for the ERA5-Land figures.

Downloads ERA5 (single levels) hourly total cloud cover for June-August 2026
over a few 0.25 deg grid points around New Haven (one small request), then
ranks days by mean cloud cover during local daylight (06-19 EDT) and, as a
tie-breaker, over the preceding night (00-05 EDT), so that both the daytime
heating and the nighttime cooling happen under clear skies.

Output: data/era5-land/selection_tcc_2026JJA.nc and a printed ranking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cdsapi
import pandas as pd
import xarray as xr

from common import config

DATASET = "era5-land"
CDS_URL = "https://cds.climate.copernicus.eu/api"
# A 2x2 block of ERA5 0.25 deg points surrounding New Haven (N, W, S, E).
AREA = [41.5, -73.0, 41.25, -72.75]


def main():
    out = config.data_dir(DATASET) / "selection_tcc_2026JJA.nc"
    if not out.exists():
        client = cdsapi.Client(url=CDS_URL, key=config.credentials()["cds_api_key"], quiet=True, progress=False)
        request = {
            "product_type": ["reanalysis"],
            "variable": ["total_cloud_cover"],
            "year": ["2026"],
            "month": ["06", "07", "08"],
            "day": [f"{d:02d}" for d in range(1, 32)],
            "time": [f"{h:02d}:00" for h in range(24)],
            "area": AREA,
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        print("requesting ERA5 total cloud cover, Jun-Aug 2026 ...")
        client.retrieve("reanalysis-era5-single-levels", request).download(str(out))
    # region clear-day-ranking
    ds = xr.open_dataset(out)
    tcc = ds["tcc"].mean(["latitude", "longitude"]).to_series()
    tcc.index = pd.DatetimeIndex(tcc.index).tz_localize("UTC").tz_convert("Etc/GMT+4")  # EDT = UTC-4
    df = tcc.rename("tcc").to_frame()
    df["date"] = df.index.date
    df["hour"] = df.index.hour
    df = df[(df.index.month >= 6) & (df.index.month <= 8)]
    day = df[(df.hour >= 6) & (df.hour <= 19)].groupby("date")["tcc"].mean()
    night = df[df.hour <= 5].groupby("date")["tcc"].mean()
    rank = pd.DataFrame({"tcc_day": day, "tcc_night": night}).dropna()
    rank["score"] = rank.tcc_day + 0.5 * rank.tcc_night
    rank = rank.sort_values("score")
    print("Clearest days (mean total cloud cover fraction, local EDT):")
    print(rank.head(15).round(3).to_string())
    # endregion clear-day-ranking


if __name__ == "__main__":
    main()
