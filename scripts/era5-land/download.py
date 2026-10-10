# /// script
# requires-python = ">=3.11"
# dependencies = ["cdsapi>=0.7.2", "xarray", "netcdf4", "numpy", "astral", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ERA5-Land hourly 2 m air temperature (t2m) for New Haven on one clear
summer day (timing.DATE), at the hours nearest sunrise, solar noon, sunset
and the middle of the preceding night, from the Copernicus Climate Data Store.

The request covers the view bounds padded by >= 2 grid cells (0.1 deg), snapped
outward to the 0.1 deg grid. Output: data/era5-land/era5-land_t2m_<date>.nc
with the four valid times.
"""

import datetime as dt
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdsapi
import numpy as np
import xarray as xr

import timing
from common import config, views

DATASET = "era5-land"
CDS_URL = "https://cds.climate.copernicus.eu/api"
RES = 0.1  # deg
PAD_CELLS = 2


def area() -> list[float]:
    """[N, W, S, E] covering all views + PAD_CELLS cells, on the 0.1 deg grid."""
    west, south, east, north = views.all_bounds_lonlat()
    p = PAD_CELLS * RES
    snap_dn = lambda v: math.floor(round(v / RES, 6)) * RES  # noqa: E731
    snap_up = lambda v: math.ceil(round(v / RES, 6)) * RES  # noqa: E731
    return [round(snap_up(north + p), 1), round(snap_dn(west - p), 1), round(snap_dn(south - p), 1), round(snap_up(east + p), 1)]


def main():
    out = config.data_dir(DATASET) / f"era5-land_t2m_{timing.DATE:%Y%m%d}.nc"
    if out.exists():
        print(f"{out.relative_to(config.REPO)} exists; skipping download")
        return
    # region days-x-hours-subset
    times_utc = sorted(h.astimezone(dt.UTC).replace(tzinfo=None) for _, h in timing.product_times().values())
    days = sorted({t.date() for t in times_utc})
    hours = sorted({t.hour for t in times_utc})
    request = {
        "variable": ["2m_temperature"],
        "year": sorted({f"{d.year}" for d in days}),
        "month": sorted({f"{d.month:02d}" for d in days}),
        "day": [f"{d.day:02d}" for d in days],
        "time": [f"{h:02d}:00" for h in hours],
        "area": area(),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    print(f"requesting ERA5-Land t2m: days {request['day']} hours {request['time']} UTC, area {request['area']}")
    client = cdsapi.Client(url=CDS_URL, key=config.credentials()["cds_api_key"], quiet=True, progress=False)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.nc"
        client.retrieve("reanalysis-era5-land", request).download(str(raw))
        with xr.open_dataset(raw) as ds:
            # the request is a days x hours product; keep only the four wanted times
            sub = ds.sel(valid_time=np.array(times_utc, dtype="datetime64[ns]")).load()
        sub.attrs["selection"] = (
            f"{timing.DATE}: hours nearest the middle of the night, sunrise, solar noon and sunset in New Haven (EDT = UTC-4)"
        )
    # endregion days-x-hours-subset
        sub.to_netcdf(out)
    print(f"wrote {out.relative_to(config.REPO)}: {[str(t)[:16] for t in sub.valid_time.values]} UTC")


if __name__ == "__main__":
    main()
