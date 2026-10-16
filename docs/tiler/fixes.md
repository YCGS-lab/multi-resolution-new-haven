# Dataset-specific fixes

GOES, SMAP and Black Marble files don't present coordinates the way titiler
expects. Instead of pre-converting the data, the openers patch the lazily
opened dataset (scale coordinates, attach a CRS, build a grid), so every
dataset is still read from the original files on request.

## GOES fixed grid

GOES ABI files store the [fixed grid](./glossary#goes-abi): `x` and `y` are
scan angles in radians from the satellite. The projection is in the
`goes_imager_projection` variable, a [CF grid mapping](./glossary#cf) with
`grid_mapping_name: geostationary`, the satellite height, the ellipsoid,
the sub-satellite longitude and the sweep axis. So the opener multiplies the
scan angles by `perspective_point_height` (meters in the geostationary
projection, as NOAA's product guide and pyproj's `+proj=geos` expect) and
sets the CRS with `pyproj.CRS.from_cf`, which includes `+sweep=x`.

::: code-group
<<< @/../tiler/src/ycgs_titiler/readers.py#goes-fix [readers.py#goes-fix]
<<< @/../tiler/src/ycgs_titiler/readers.py#grid-mapping [readers.py#grid-mapping]
:::

The coordinate arrays are 1-D (2500 and 1500 values for CONUS), so scaling
them is cheap and reads no data. The same CF-to-CRS logic is used whenever a
variable has no CRS of its own. The pipeline places the pre-built GOES LST
the same way ([fixed-grid georeferencing](/pipeline/datasets/temperature#fixed-grid-georeferencing)).

::: warning Design decision: keyed on the file's content, not its URL
The fix-up runs when `goes_imager_projection` is present, so every ABI L1b /
L2 product read through `/xarray` is placed correctly: `red-500m`
(`ABI-L2-CMIPC`) and `goes19-lst` (`ABI-L2-LSTC`) needed no extra code.
:::

## Grouped HDF5 (SMAP L4) {#grouped-hdf5}

SMAP L4 files (`SPL4SMGP`) put the data variables in the HDF5 group
`/Geophysical_Data`, while the `x` / `y` coordinate arrays and the
EASE-Grid 2.0 grid-mapping variable sit in the root group. Opened with
`group=Geophysical_Data`, xarray sees only that group: `sm_rootzone` with
dimensions but no coordinate values and no CRS, which titiler cannot place.

::: code-group
<<< @/../tiler/src/ycgs_titiler/readers.py#grouped-reader [readers.py#grouped-reader]
:::

`open_dataset_with_root_coords` wraps titiler-cmr's own `open_dataset`, so
it keeps titiler-cmr's Earthdata credentials and its cache. Then:

1. If the group already has `x` and `y` coordinates, nothing changes.
2. If it has 1-D `lat` / `lon` variables, it is an
   [HDF-EOS5 lat/lon grid](#hdf-eos5-lat-lon-grids).
3. Otherwise (and if a group was asked for) it opens the root group too
   (cached by titiler-cmr: one extra metadata read per file), renames the
   group's dimensions to `x` / `y` by matching their sizes to the root's
   (covers both real dimension names and h5netcdf's `phony_dim_N`), copies
   the coordinate values, and writes the CRS from the root's grid mapping.

### Data files only

::: danger Workaround: `data_first`
titiler-cmr's xarray reader opens the granule's asset `"0"`, and it keys
assets by file name *without extension*. A SMAP L4 granule lists both
`<name>.h5` and a `<name>.qa` quality report, so the `.qa` file replaced the
`.h5`: the reader opened the quality report instead of the data. `data_first` keeps only the
HDF5 / NetCDF links among a granule's related URLs (when there are any)
before the reader picks its asset.
:::

### Small variables read once

::: warning Design decision: keep fully read small granule variables in memory
SMAP L4 stores each global variable as one compressed chunk, so every tile
would decompress the whole global field again. After the first read, the
grouped reader loads a variable of at most 64 MB (`LOADED_MAX_BYTES`) into
memory and keeps it in a second LRU, `_loaded` (8 entries,
`YCGS_LOADED_CACHE_SIZE`), keyed by the granule's file, group, variables,
expression and `sel`. Later tiles of the same granule skip titiler-cmr's
opening and selection and go straight to rio-tiler's reader setup. The
memory cost is bounded by 8 × 64 MB; the cache is cleared with the dataset
cache after a SnapStart restore.
:::

`GroupedXarrayGranuleReader` is served by an extra titiler-cmr factory at
`/cmr/xarray-grouped` ([application](./app#mounting-titiler-cmr)).

::: warning Design decision: a separate backend, not a patch to titiler-cmr's
It does not replace the reader of titiler-cmr's own `/cmr/xarray` routes:
titiler-cmr's time-series code checks `factory.dataset_reader ==
XarrayGranuleReader` and would treat a substitute as the rasterio backend,
and the upstream routes stay unmodified for other collections. The cost is
one more set of routes and a backend name, `cmr-xarray-grouped`.
:::

## HDF-EOS5 lat/lon grids (Black Marble) {#hdf-eos5-lat-lon-grids}

VNP46A4 tiles are [HDF-EOS5](./glossary#hdf-eos5) grids: the data fields
sit in `HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields` next to 1-D `lat` and
`lon` variables but no coordinates.
`latlon_grid` builds an EPSG:4326 dataset from them: every variable of
shape (lat, lon) on `y` / `x` coordinates.

::: danger Workaround: corners shifted to centers
The `lat` / `lon` arrays of VNP46A4 give each cell's **upper-left corner**
(the first values are the tile's whole-degree edges), while xarray and
rio-tiler treat coordinates as cell centers. Taken as is, the image would
be half a cell off to the north-west. When both arrays start on a
whole degree, `latlon_grid` shifts them by half a step. The pipeline
checks the same grid against the file's metadata
([Black Marble](/pipeline/datasets/water-and-lights#viirs-black-marble)).
:::

::: code-group
<<< @/../tiler/tests/test_readers.py#latlon-grid [test_readers.py#latlon-grid]
:::
