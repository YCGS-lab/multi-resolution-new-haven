"""Xarray readers.

- `MultiVarReader` (the /xarray endpoints): opens a Zarr store or a NetCDF/HDF5
  file by URL and stacks one or more variables into bands b1..bn, like
  titiler-cmr's `variables`. `sel` is applied to each lazy variable before any
  data is read, so a time step costs only the chunks of that time step.
- `GroupedXarrayGranuleReader` (the /cmr/xarray-grouped endpoints): titiler-cmr's
  granule reader for HDF5 files whose data variables sit in a group without
  coordinates: x/y and the grid mapping from the root group (SMAP L4), from
  1-D lat/lon variables (HDF-EOS5 geographic grids, Black Marble) or from the
  grid group's XDim/YDim (HDF-EOS5 projected grids, VIIRS LST VNP21A1D).
"""

from __future__ import annotations

import os
import threading
import urllib.parse
from collections.abc import Callable
from functools import cache
from typing import Any, Literal

import attr
import numpy as np
import obstore.store
import xarray as xr
from cachetools import LRUCache
from morecantile import TileMatrixSet
from obspec_utils.readers import BlockStoreReader
from pyproj import CRS
from rio_tiler.constants import WEB_MERCATOR_TMS
from rio_tiler.io.xarray import Options, XarrayReader
from titiler.cmr.expression import apply_expression
from titiler.cmr.reader import X_DIM_NAMES, Y_DIM_NAMES, XarrayGranuleReader, _arrange_dims
from titiler.cmr.reader import open_dataset as cmr_open_dataset
from titiler.xarray.io import _find_bucket_region, _parse_dsl
from zarr.storage import ObjectStore

# region constants
# Host whose requests carry the Copernicus CDS API key (ERA5-Land ARCO Zarr).
CDS_ARCO_HOST = "arco.datastores.ecmwf.int"
# S3 buckets read anonymously (public NOAA Open Data).
PUBLIC_BUCKET_PREFIXES = ("noaa-",)
NETCDF_SUFFIXES = (".nc", ".nc4", ".h5", ".hdf5", ".he5")

_datasets: LRUCache = LRUCache(maxsize=int(os.environ.get("YCGS_DATASET_CACHE_SIZE", "16")))
_lock = threading.Lock()
# Fully read granule variables (GroupedXarrayGranuleReader), by granule file and selection.
_loaded: LRUCache = LRUCache(maxsize=int(os.environ.get("YCGS_LOADED_CACHE_SIZE", "8")))
LOADED_MAX_BYTES = 64 * 1024**2
# endregion constants


class URLNotAllowed(ValueError):
    pass


class MissingCredentials(RuntimeError):
    """A data source needs a credential this deployment doesn't have."""


# region allowlist
def allowed_prefixes() -> tuple[str, ...]:
    """URL prefixes /xarray and /cog may open (YCGS_ALLOWED_URL_PREFIXES, comma separated).

    Keeps the endpoint from being used to fetch arbitrary URLs, and keeps the
    CDS key from being sent anywhere but the CDS ARCO host.
    """
    raw = os.environ.get(
        "YCGS_ALLOWED_URL_PREFIXES",
        f"s3://noaa-goes19/,s3://noaa-goes18/,https://{CDS_ARCO_HOST}/,https://data.chc.ucsb.edu/products/CHIRPS/",
    )
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def check_url(url: str) -> None:
    if not any(url.startswith(p) for p in allowed_prefixes()):
        raise URLNotAllowed(f"URL not allowed: {url}")


# endregion allowlist


@cache
def bucket_region(bucket: str) -> str:
    return _find_bucket_region(bucket) or os.environ.get("AWS_REGION", "us-east-1")


# region stores
def _store(url: str):
    """obstore store rooted at `url` (scheme, host and path prefix)."""
    parsed = urllib.parse.urlparse(url)
    prefix = parsed.path.strip("/") or None
    if parsed.scheme == "s3":
        config: dict[str, Any] = {"region": bucket_region(parsed.netloc)}
        if parsed.netloc.startswith(PUBLIC_BUCKET_PREFIXES):
            config["skip_signature"] = True
        return obstore.store.S3Store(parsed.netloc, prefix=prefix, config=config)
    if parsed.scheme in ("http", "https"):
        client_options: dict[str, Any] = {}
        if parsed.netloc == CDS_ARCO_HOST:
            key = os.environ.get("YCGS_CDS_API_KEY")
            if not key:
                raise MissingCredentials("YCGS_CDS_API_KEY is not set (CDS API key for the ERA5-Land ARCO store)")
            client_options["default_headers"] = {"Authorization": f"Bearer {key}"}
        return obstore.store.HTTPStore.from_url(url.rstrip("/"), client_options=client_options)
    if parsed.scheme == "file":  # local development and tests
        return obstore.store.LocalStore(prefix=f"/{prefix}" if prefix else "/")
    raise URLNotAllowed(f"unsupported URL scheme: {url}")


# endregion stores


# region grid-mapping
def crs_from_grid_mapping(ds: xr.Dataset) -> CRS | None:
    """CRS from a CF grid-mapping variable (one with a `grid_mapping_name` attribute)."""
    for name in ds.variables:
        if "grid_mapping_name" in ds[name].attrs:
            return CRS.from_cf(ds[name].attrs)
    return None


# endregion grid-mapping


# region goes-fix
def fix_goes(ds: xr.Dataset) -> xr.Dataset:
    """GOES ABI fixed grid: x/y are scan angles (radians); scale them to meters
    on the geostationary projection and set that CRS."""
    if "goes_imager_projection" not in ds.variables:
        return ds
    proj = ds["goes_imager_projection"].attrs
    h = float(proj["perspective_point_height"])
    ds = ds.assign_coords(x=ds["x"].values * h, y=ds["y"].values * h)
    return ds.rio.write_crs(CRS.from_cf(proj))


# endregion goes-fix


# region open-dataset
def open_dataset(src_path: str, group: str | None = None, decode_times: bool = True, **kwargs) -> xr.Dataset:
    """Open a Zarr store or NetCDF/HDF5 file lazily; cached per execution environment."""
    check_url(src_path)
    key = (src_path, group, decode_times)
    if (ds := _datasets.get(key)) is not None:
        return ds
    with _lock:
        if (ds := _datasets.get(key)) is not None:
            return ds
        parsed = urllib.parse.urlparse(src_path)
        args: dict[str, Any] = {"decode_times": decode_times, "decode_coords": "all", "group": group}
        if parsed.path.lower().endswith(NETCDF_SUFFIXES):
            store = _store(f"{parsed.scheme}://{parsed.netloc}")
            reader = BlockStoreReader(store, parsed.path.lstrip("/"), block_size=4 * 1024**2)
            ds = xr.open_dataset(reader, engine="h5netcdf", lock=False, phony_dims="sort", chunks={}, **args)
        else:
            ds = xr.open_dataset(ObjectStore(_store(src_path), read_only=True), engine="zarr", **args)
        ds = fix_goes(ds)
        _datasets[key] = ds
        return ds


# endregion open-dataset


def clear_caches() -> None:
    """Drop cached datasets/stores (e.g. after a SnapStart restore)."""
    with _lock:
        _datasets.clear()
        _loaded.clear()
    bucket_region.cache_clear()


# region select
def _select(da: xr.DataArray, sel: list[str] | None) -> xr.DataArray:
    """titiler.xarray's `sel` DSL ({dim}={value} or {dim}={method}::{value}),
    applied only to dimensions the variable has."""
    for s in _parse_dsl(sel):
        dim, values, method = s["dimension"], s["values"], s["method"]
        if dim not in da.dims:
            continue
        if da[dim].dtype != "O":
            values = [
                da[dim].dtype.type(v.rstrip("Z") if np.issubdtype(da[dim].dtype, np.datetime64) else v) for v in values
            ]
        da = da.sel({dim: values[0] if len(values) < 2 else values}, method=method)
    return da


# endregion select


# region get-variables
def get_variables(
    ds: xr.Dataset,
    variables: list[str],
    sel: list[str] | None = None,
    expression: str | None = None,
) -> xr.DataArray:
    """Stack `variables` (after `sel`) into a (band, y, x) DataArray and apply `expression`.

    With one variable, a remaining non-spatial dimension (e.g. two selected
    times) becomes the band dimension.
    """
    missing = [v for v in variables if v not in ds.variables]
    if missing:
        raise KeyError(f"variables not found: {missing}; available: {sorted(map(str, ds.data_vars))}")
    spatial = set(X_DIM_NAMES + Y_DIM_NAMES + ["x", "y"])
    arrays = []
    for v in variables:
        da = _select(ds[v], sel)
        da = da.squeeze([d for d in da.dims if d not in spatial and da.sizes[d] == 1], drop=True)
        arrays.append(da)
    if len(arrays) == 1:
        da = arrays[0]
        extra = [d for d in da.dims if d not in spatial]
        if len(extra) > 1:
            raise ValueError(f"{variables[0]} still has dimensions {extra}; select them with `sel`")
        da = da.rename({extra[0]: "band"}) if extra else da.expand_dims("band")
    else:
        for v, a in zip(variables, arrays):
            if extra := [d for d in a.dims if d not in spatial]:
                raise ValueError(f"{v} still has dimensions {extra}; select them with `sel`")
        da = xr.concat(arrays, dim="band", coords="minimal", compat="override", join="override")
    da = _arrange_dims(da, x_dim_names=X_DIM_NAMES, y_dim_names=Y_DIM_NAMES)
    crs = da.rio.crs or crs_from_grid_mapping(ds) or "epsg:4326"
    da = da.rio.write_crs(crs)
    if expression:
        da = apply_expression(da, expression)
    if da.rio.crs == "epsg:4326" and (da.x > 180).any():
        da = da.assign_coords(x=(da.x + 180) % 360 - 180).sortby("x")
    return da


# endregion get-variables


# region multivar-reader
@attr.s
class MultiVarReader(XarrayReader):
    """titiler.xarray reader for one or more variables of a dataset at `src_path`."""

    src_path: str = attr.ib()
    variables: list[str] = attr.ib()

    opener: Callable[..., xr.Dataset] = attr.ib(default=open_dataset)
    opener_options: dict = attr.ib(factory=dict)

    group: str | None = attr.ib(default=None)
    decode_times: bool = attr.ib(default=True)
    sel: list[str] | None = attr.ib(default=None)
    method: Literal["nearest", "pad", "ffill", "backfill", "bfill"] | None = attr.ib(default=None)
    expression: str | None = attr.ib(default=None)

    tms: TileMatrixSet = attr.ib(default=WEB_MERCATOR_TMS)
    options: Options = attr.ib(factory=dict)

    ds: xr.Dataset = attr.ib(init=False)
    input: xr.DataArray = attr.ib(init=False)
    _dims: list = attr.ib(init=False, factory=list)

    def __attrs_post_init__(self):
        opts = {"group": self.group, "decode_times": self.decode_times if self.decode_times is not None else True}
        self.ds = self.opener(self.src_path, **opts, **self.opener_options)
        self.input = get_variables(self.ds, self.variables, sel=self.sel, expression=self.expression)
        super().__attrs_post_init__()

    def close(self):
        # Datasets are cached and shared between requests; nothing to close.
        pass


# endregion multivar-reader


# region grouped-reader
def _on_degree(v: float) -> bool:
    return abs(v - round(v)) < 1e-9


def latlon_grid(ds: xr.Dataset) -> xr.Dataset:
    """Geographic grid whose 1-D `lat` / `lon` are variables, not coordinates
    (HDF-EOS5 grids such as Black Marble VNP46A4): the 2-D variables of shape
    (lat, lon) on y/x coordinates, EPSG:4326.

    When both arrays start on a whole degree (a tile edge), they give each
    cell's upper-left corner, as in VNP46A4; they are shifted to cell centers.
    """
    lat, lon = ds["lat"].values.astype("float64"), ds["lon"].values.astype("float64")
    if lat.size > 1 and lon.size > 1 and _on_degree(lat[0]) and _on_degree(lon[0]):
        lat = lat + (lat[1] - lat[0]) / 2
        lon = lon + (lon[1] - lon[0]) / 2
    data = {
        name: xr.DataArray(v.data, dims=("y", "x"), attrs={k: a for k, a in v.attrs.items() if k != "coordinates"})
        for name, v in ds.data_vars.items()
        if v.shape == (lat.size, lon.size)
    }
    return xr.Dataset(data, coords={"y": lat, "x": lon}).rio.write_crs("epsg:4326")


def hdfeos_projected_grid(ds: xr.Dataset, grid: xr.Dataset) -> xr.Dataset:
    """HDF-EOS5 projected grid (VIIRS L3 such as VNP21A1D, sinusoidal): the 2-D
    (YDim, XDim) variables of a "Data Fields" group on y/x coordinates from the
    grid group's XDim / YDim, with the CRS of the CF grid-mapping variable next
    to the data.

    XDim / YDim are the cells' upper-left corners (GridOrigin UL: XDim[0] is
    StructMetadata's UpperLeftPointMtrs); they are shifted to cell centers.
    Fill values are given as `_Fillvalue`, which CF decoding ignores; those
    cells are masked here.
    """
    x, y = grid["XDim"].values.astype("float64"), grid["YDim"].values.astype("float64")
    x = x + (x[1] - x[0]) / 2
    y = y + (y[1] - y[0]) / 2
    data = {}
    for name, v in ds.data_vars.items():
        if v.dims != ("YDim", "XDim"):
            continue
        fill = np.ravel(v.attrs.get("_Fillvalue", []))
        if fill.size and np.issubdtype(fill.dtype, np.number):
            # the decoded value of the stored fill
            v = v.where(v != fill[0] * v.encoding.get("scale_factor", 1) + v.encoding.get("add_offset", 0))
        attrs = {k: a for k, a in v.attrs.items() if k not in ("coordinates", "grid_mapping", "_Fillvalue")}
        # (decoded as float64; scaled 8 / 16-bit integers fit float32)
        data[name] = xr.DataArray(v.data.astype("float32"), dims=("y", "x"), attrs=attrs)
    out = xr.Dataset(data, coords={"y": y, "x": x})
    crs = crs_from_grid_mapping(ds)
    return out.rio.write_crs(crs) if crs else out


def open_dataset_with_root_coords(src_path: str, group: str | None = None, **kwargs) -> xr.Dataset:
    """titiler-cmr's opener, plus x/y coordinates: from 1-D `lat`/`lon` variables in
    the group (HDF-EOS5 geographic grids), from the parent group's XDim / YDim
    (HDF-EOS5 projected grids), or with the grid mapping from the root group when
    `group` has its dimensions but not their coordinate variables (SMAP L4)."""
    ds = cmr_open_dataset(src_path, group=group, **kwargs)
    if "x" in ds.coords and "y" in ds.coords:
        return ds
    if all(n in ds.variables and ds[n].ndim == 1 for n in ("lat", "lon")):
        return latlon_grid(ds)
    if group in (None, "", "/"):
        return ds
    if {"YDim", "XDim"} <= set(ds.dims) and "/" in group.strip("/"):
        grid = cmr_open_dataset(src_path, group=group.strip("/").rsplit("/", 1)[0], **kwargs)
        if "XDim" in grid.variables and "YDim" in grid.variables:
            return hdfeos_projected_grid(ds, grid)
    root = cmr_open_dataset(src_path, group=None, **kwargs)
    # Dimensions may be named after the root dimension scales or be phony; match by size.
    renames = {}
    for dim, size in ds.sizes.items():
        for name in ("x", "y"):
            if dim != name and name in root.sizes and root.sizes[name] == size and name not in ds.dims:
                renames[dim] = name
    ds = ds.rename(renames)
    ds = ds.assign_coords({n: root[n].values for n in ("x", "y") if n in ds.dims and n in root.variables})
    if crs := crs_from_grid_mapping(root):
        ds = ds.rio.write_crs(crs)
    return ds


DOWNLOAD_URL_TYPES = ("GET DATA", "GET DATA VIA DIRECT ACCESS")


def data_first(granule):
    """The granule without the download links to its non-data files (when it has
    HDF5 / NetCDF data files), and with an S3 credentials endpoint.

    titiler-cmr's xarray reader opens asset "0" and keys assets by file name
    without extension, so SMAP L4's `<name>.qa` replaced `<name>.h5`. Other
    related URLs stay: the S3 credentials endpoint is one of them.
    """
    urls = list(granule.related_urls)
    downloads = [ru for ru in urls if ru.type in DOWNLOAD_URL_TYPES]
    if any(ru.url.lower().endswith(NETCDF_SUFFIXES) for ru in downloads):
        urls = [ru for ru in urls if ru.type not in DOWNLOAD_URL_TYPES or ru.url.lower().endswith(NETCDF_SUFFIXES)]
    # LAADS granules (Black Marble) do not list their DAAC's S3 credentials
    # endpoint; it is /s3credentials on the host of the HTTPS download links.
    if not any("/s3credentials" in ru.url for ru in urls):
        https = next((ru for ru in downloads if ru.type == "GET DATA" and ru.url.startswith("https://")), None)
        if https is not None:
            host = urllib.parse.urlparse(https.url).netloc
            urls.append(
                https.model_copy(update={"type": "VIEW RELATED INFORMATION", "url": f"https://{host}/s3credentials"})
            )
    return granule.model_copy(update={"related_urls": urls})


@attr.s
class GroupedXarrayGranuleReader(XarrayGranuleReader):
    opener: Callable[..., xr.Dataset] = attr.ib(default=open_dataset_with_root_coords)

    def __attrs_post_init__(self):
        self.src_path = data_first(self.src_path)
        asset = self.src_path.get_assets()["0"]
        href = asset.direct_href if self.s3_access else asset.external_href
        key = (href, self.group, tuple(self.variables), self.expression, tuple(self.sel or ()))
        if (hit := _loaded.get(key)) is not None:
            self.ds, self.input = hit
            XarrayReader.__attrs_post_init__(self)
            return
        super().__attrs_post_init__()
        # Small global grids stored as one compressed chunk (SMAP L4: one gzip
        # chunk per variable): read them once per warm instance, not per tile.
        if self.input.nbytes <= LOADED_MAX_BYTES:
            self.input = self.input.load()
            with _lock:
                _loaded[key] = (self.ds, self.input)


# endregion grouped-reader
