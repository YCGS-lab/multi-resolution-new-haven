import datetime as dt
import os

import numpy as np
import pandas as pd
import pytest
import xarray as xr

# Local files are allowed in tests (file:// URLs).
os.environ.setdefault("YCGS_ALLOWED_URL_PREFIXES", "file:///,s3://noaa-goes19/,https://arco.datastores.ecmwf.int/")


@pytest.fixture(scope="session")
def era5_like(tmp_path_factory) -> str:
    """Hourly Zarr like the CDS ARCO ERA5-Land store: (time, latitude, longitude), K."""
    times = pd.date_range("2026-07-20T00:00", periods=24, freq="h")
    lat = np.arange(42.0, 40.9, -0.1)
    lon = np.arange(-74.0, -71.9, 0.1)
    data = 290.0 + np.arange(24, dtype="float32")[:, None, None] + np.zeros((1, lat.size, lon.size), "float32")
    ds = xr.Dataset(
        {"2m_temperature": (("time", "latitude", "longitude"), data, {"units": "K"})},
        coords={"time": times, "latitude": lat, "longitude": lon},
    )
    path = tmp_path_factory.mktemp("zarr") / "era5.zarr"
    ds.chunk({"time": 1}).to_zarr(path, zarr_format=3, consolidated=False)
    return f"file://{path}"


@pytest.fixture(scope="session")
def multivar_nc(tmp_path_factory) -> str:
    """NetCDF with two variables on a lon/lat grid."""
    lat = np.linspace(41.5, 41.0, 6)
    lon = np.linspace(-73.2, -72.6, 7)
    shape = (lat.size, lon.size)
    ds = xr.Dataset(
        {"a": (("lat", "lon"), np.full(shape, 4.0, "float32")), "b": (("lat", "lon"), np.full(shape, 1.0, "float32"))},
        coords={"lat": lat, "lon": lon},
    )
    path = tmp_path_factory.mktemp("nc") / "multi.nc"
    ds.to_netcdf(path, engine="h5netcdf")
    return f"file://{path}"


def utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.UTC)
