"""Dataset presets (datasets.yaml): which backend serves a dataset, its fixed
query parameters, how a requested time becomes backend parameters, and its
named renders (band combinations / color scaling)."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# Query parameters: scalars or lists of scalars (lists become repeated keys).
Params = dict[str, Any]

# region backend-prefix
# backend -> path prefix of the titiler endpoints inside this app
BACKEND_PREFIX = {
    "cmr-xarray": "/cmr/xarray",  # titiler-cmr, xarray (NetCDF/HDF5 granules)
    "cmr-xarray-grouped": "/cmr/xarray-grouped",  # same, but borrows x/y/CRS from the root group
    "cmr-rasterio": "/cmr/rasterio",  # titiler-cmr, rasterio (COG granules)
    "xarray": "/xarray",  # titiler.xarray with YCGS opener (Zarr / NetCDF by URL)
    "cog": "/cog",  # titiler.core with rio-tiler (Cloud-Optimized GeoTIFF by URL)
}
CMR_BACKENDS = {"cmr-xarray", "cmr-xarray-grouped", "cmr-rasterio"}
# endregion backend-prefix


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# region time-specs
class GranuleTime(_Model):
    """CMR granule selection: `datetime` becomes the CMR `temporal` filter."""

    kind: Literal["granule"]
    # day / month / year: the whole UTC day, month or year containing `datetime`
    # (newest granule first); instant: granules whose time range contains
    # `datetime`. A `start/end` interval is used as is.
    align: Literal["day", "month", "year", "instant"] = "day"
    default: str | None = None  # None: no time filter (static collections)


class DimensionTime(_Model):
    """A time dimension inside one dataset: `datetime` becomes `sel={dim}={method}::{T}`,
    applied lazily so only the chunks for that time step are read."""

    kind: Literal["dimension"]
    dim: str = "time"
    method: Literal["nearest", "pad", "ffill", "backfill", "bfill"] | None = "nearest"
    default: str


class ScanTime(_Model):
    """One file per scan (GOES ABI on NOAA Open Data): `datetime` becomes the
    S3 key of the nearest scan; no `datetime` means the latest scan."""

    kind: Literal["scan"]
    bucket: str
    product: str  # e.g. ABI-L2-MCMIPC
    channel: str | None = None  # e.g. C02 for single-channel products (ABI-L2-CMIPC)
    default: str | None = None  # None: latest scan


class TemplateTime(_Model):
    """One file per time step at a predictable URL (CHIRPS daily COGs):
    `datetime` fills the strftime fields of `url` ({t:%Y.%m.%d})."""

    kind: Literal["template"]
    url: str
    step: Literal["day", "month", "year"] = "day"
    default: str
    # Latest step published, as days behind today (to list available times)
    latency_days: int = 0


class StaticTime(_Model):
    """No time dimension (a DEM)."""

    kind: Literal["static"]


TimeSpec = Annotated[GranuleTime | DimensionTime | ScanTime | TemplateTime | StaticTime, Field(discriminator="kind")]
# endregion time-specs


# region render-model
class ZoomParams(_Model):
    """Parameters used up to and including `maxzoom` (the last entry may omit it)."""

    maxzoom: int | None = None
    params: Params


class Render(_Model):
    title: str
    description: str | None = None
    params: Params = Field(default_factory=dict)
    # Overrides of the dataset's time spec fields (e.g. a different GOES product)
    time: dict[str, Any] = Field(default_factory=dict)
    maxzoom: int | None = None
    # The render compares two times (`datetime` and `datetime2`; dimension time only)
    two_times: bool = False


# endregion render-model


# region dataset-model
class Dataset(_Model):
    title: str
    description: str | None = None
    attribution: str | None = None
    # Regional deployment that serves it (CloudFront routes /datasets/{id}/* there)
    deployment: Literal["nasa", "noaa", "ecmwf"]
    backend: Literal["cmr-xarray", "cmr-xarray-grouped", "cmr-rasterio", "xarray", "cog"]
    params: Params = Field(default_factory=dict)
    zooms: list[ZoomParams] = Field(default_factory=list)
    time: TimeSpec
    bounds: tuple[float, float, float, float] = (-180.0, -85.0511287798066, 180.0, 85.0511287798066)
    minzoom: int = 0
    maxzoom: int = 14
    renders: dict[str, Render]

    @property
    def prefix(self) -> str:
        return BACKEND_PREFIX[self.backend]

    def zoom_params(self, z: float | None) -> Params:
        if not self.zooms:
            return {}
        if z is None:
            return dict(self.zooms[-1].params)
        for zp in self.zooms:
            if zp.maxzoom is None or z <= zp.maxzoom + 1e-9:
                return dict(zp.params)
        return dict(self.zooms[-1].params)

    def time_for(self, render: Render) -> GranuleTime | DimensionTime | ScanTime | TemplateTime | StaticTime:
        return self.time.model_copy(update=render.time) if render.time else self.time


# endregion dataset-model


# region catalog-load
class Catalog(_Model):
    aoi: tuple[float, float, float, float]  # lon/lat box used to list available times
    datasets: dict[str, Dataset]


DEFAULT_PATH = Path(__file__).with_name("datasets.yaml")


def load(path: str | Path | None = None) -> Catalog:
    path = Path(path or os.environ.get("YCGS_DATASETS_FILE") or DEFAULT_PATH)
    return Catalog.model_validate(yaml.safe_load(path.read_text()))


@cache
def catalog() -> Catalog:
    return load()


# endregion catalog-load
