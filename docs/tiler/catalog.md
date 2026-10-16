# Catalog: `datasets.yaml`

`tiler/src/ycgs_titiler/datasets.yaml` lists every dataset preset once:
which regional deployment serves it, which backend reads it, its fixed
parameters, how a time is selected, and its named renders. Two programs
read it:

- the app, through the pydantic models in `presets.py`;
- OpenTofu (`terraform/tiler/cloudfront.tf`), which routes each dataset to
  its region ([CloudFront](./cloudfront#routes-from-the-catalog)).

## Header

Expressions refer to bands *by position* (`b1`, `b2`, ...), a YAML list
becomes a repeated query parameter, and `aoi` is the area used when listing
available times from CMR.

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#header [datasets.yaml#header]
:::

## Schema <Badge type="tip" text="standard" />

Plain [pydantic](https://docs.pydantic.dev/) models. `extra="forbid"` makes
a typo in `datasets.yaml` fail at startup instead of being ignored;
`frozen=True` makes them immutable.

Each `backend` is a path prefix inside this app:

::: code-group
<<< @/../tiler/src/ycgs_titiler/presets.py#backend-prefix [presets.py#backend-prefix]
:::

- three titiler-cmr routers under `/cmr`; `cmr-xarray-grouped` is our own
  addition ([fixes](./fixes#grouped-hdf5));
- titiler.xarray with our reader at `/xarray` ([readers](./readers));
- titiler.core's COG endpoints at `/cog`, for COGs by URL
  ([application](./app#backends)).

The time specification is a *discriminated union* on `kind`: pydantic picks
the model from the `kind` field. The five kinds are explained on
[Time resolution](./time).

::: code-group
<<< @/../tiler/src/ycgs_titiler/presets.py#time-specs [presets.py#time-specs]
:::

A render can add or override parameters (variables, assets, expression,
rescale, colormap), override fields of the time spec (GOES `red-500m`
reads a different product), cap the zoom, and declare `two_times` for
difference renders.

::: code-group
<<< @/../tiler/src/ycgs_titiler/presets.py#render-model [presets.py#render-model]
<<< @/../tiler/src/ycgs_titiler/presets.py#dataset-model [presets.py#dataset-model]
:::

The dataset model adds `zooms` (parameters chosen by zoom level), the
backend `prefix`, and `time_for(render)`: the dataset's time spec with the
render's overrides applied.

The catalog is loaded once per process (`@cache`). `main.py` loads it at
import, so a broken `datasets.yaml` fails the image build (the Dockerfile's
import check) and never reaches Lambda. `YCGS_DATASETS_FILE` points it at
another file (the app tests use a one-dataset catalog).

::: code-group
<<< @/../tiler/src/ycgs_titiler/presets.py#catalog-load [presets.py#catalog-load]
:::

## NASA datasets (us-west-2)

### NISAR GCOV {#nisar}

Radar backscatter read by titiler-cmr from ASF's HDF5 granules: the two
covariance terms `HHHH` and `HVHV` (linear power).

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#nisar [datasets.yaml#nisar]
:::

::: warning Design decision: the browser's composites, computed on the server
The [titiler-cmr-browser](https://developmentseed.org/titiler-cmr-browser/)
draws its NISAR composites in the browser from raw tiles. Here the same
channels and dB ranges (also used by the pipeline's
[`nisar-gcov` figures](/pipeline/datasets/radar)) become one titiler
`expression` with three `;`-separated outputs and one `rescale` per output:
HH = `10*log10(b1)` [−20, 0] dB, HV = `10*log10(b2)` [−30, 5] dB,
HH/HV = `10*log10(b1/b2)` [2, 18] dB. The four RGBs differ only in which
channel goes to red, green and blue.
:::

::: warning Design decision: zoom-dependent HDF5 group
NISAR GCOV has two grids: frequency A (10 m) and the coarser frequency B.
As in titiler-cmr-browser, the preset reads frequency B up to zoom 9 and
frequency A from zoom 10, so overview tiles read far fewer bytes. For bbox
requests the zoom comes from the requested resolution
([request rewriting](./requests#zoom-dependent-parameters)).
:::

### SMAP L4 soil moisture {#smap}

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#smap [datasets.yaml#smap]
:::

The data variables are in an HDF5 group whose coordinates sit in the root
group, hence the `cmr-xarray-grouped` backend
([SMAP grouped HDF5](./fixes#grouped-hdf5)). `align: instant` selects the
3-hourly granule containing the time; the website instead sends the
granule's window (`start/end`), which is used as is.

### HLS (Landsat) {#hls}

Harmonized Landsat Sentinel-2, Landsat part. Each band is a separate COG, so
this uses titiler-cmr's **rasterio** backend: `assets_regex` names the
assets by the `B[0-9][0-9]` part of the file names, and `assets` selects
them in the order the expression or RGB uses them. The combinations match
the website's [Landsat products](/pipeline/datasets/optical#landsat-8).

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#hls [datasets.yaml#hls]
:::

### VIIRS Black Marble {#blackmarble}

The annual VNP46A4 composite: 10 × 10° HDF-EOS5 tiles from LAADS. A date
selects that year's tiles (`align: year`); the radiance is shown on a log
scale, as on the [website](/pipeline/datasets/water-and-lights#viirs-black-marble).

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#blackmarble [datasets.yaml#blackmarble]
:::

The files have no x/y coordinates, only 1-D `lat` / `lon` arrays giving cell
corners. The grouped backend turns them into a grid
([HDF-EOS5 lat/lon grids](./fixes#hdf-eos5-lat-lon-grids)).

### ASTER GDEM {#aster}

One time-less collection of 1 × 1° GeoTIFF tiles, read by titiler-cmr's
rasterio backend. The time kind `static` adds no `temporal` filter, so CMR
returns the tiles over the requested area.

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#aster [datasets.yaml#aster]
:::

## NOAA and CHIRPS (us-east-1)

### GOES-19 ABI imagery {#goes}

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#goes [datasets.yaml#goes]
:::

- `ABI-L2-MCMIPC` holds all 16 bands on the 2 km grid in one file per scan,
  so a three-band composite is one file and one request. That is why the
  reader [stacks several variables into bands](./readers#stacking-into-bands).
- ABI has no green band. `truecolor` builds a "synthetic green" from red,
  the 0.86 µm "veggie" band and blue (0.45 / 0.10 / 0.45), a common simple
  approximation.
- `red-500m` overrides the time spec's `product` and `channel`: the same
  scan time resolves to the single-band 0.5 km file.

### GOES-19 land surface temperature {#goes-lst}

The same mechanism for the hourly `ABI-L2-LSTC` product. The `raw` render
returns `LST` and the quality flag `DQF`; the website keeps DQF 0–1, as
the pre-built [GOES LST](/pipeline/datasets/temperature#goes-lst) COG does.

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#goes-lst [datasets.yaml#goes-lst]
:::

### CHIRPS daily {#chirps}

One COG per day at a predictable URL on the Climate Hazards Center's server,
read by the `/cog` backend. The server sends no CORS headers, so a browser
cannot read the files itself; the tiler can. `latency_days` bounds the
times listed as available (the "final" stream appears about 45 days late).
The tiler runs in us-east-1 for this one only because that is the default
deployment; the data are not on AWS.

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#chirps [datasets.yaml#chirps]
:::

## ERA5-Land (ecmwf) {#era5-land}

::: code-group
<<< @/../tiler/src/ycgs_titiler/datasets.yaml#era5 [datasets.yaml#era5]
:::

::: warning Design decision: read ECMWF's analysis-ready Zarr directly
ECMWF publishes ERA5-Land as [ARCO](./glossary#arco) Zarr stores, read
directly with a CDS API key, in two layouts: time-chunked (for maps) and
geo-chunked (for time series at a point). The preset uses the time-chunked
store, the same one the [website reads](/website/time#era5-land-from-an-arco-zarr-store)
in the browser. A `datetime` becomes a lazy nearest-neighbour `sel` on
`time`, so a tile reads only that hour's chunks. The variable is `t2m`.

The alternative, copying a subset into our own S3, is fast but limited to
whatever was copied.
:::

## Renders {#renders}

A render is a set of extra query parameters (and optionally time-spec
overrides) with a title. For example, `goes19-abi/truecolor` contributes
`variables=CMI_C02&variables=CMI_C03&variables=CMI_C01`,
`expression=b1;0.45*b1+0.1*b2+0.45*b3;b3`, three `rescale` values and
`color_formula=gamma rgb 2.2`. titiler applies the expression and the color
operations after reading; on the xarray backends the expression is
evaluated on the lazy arrays ([readers](./readers#expressions)).

::: warning Design decision: server-side composites, plus `raw`
Server-side composites give small, cacheable PNGs that any map client
(deck.gl, MapLibre, Leaflet) can show without shaders. The cost: a new color
stretch means new tiles rather than re-coloring cached data. Clients that
want that use the `raw` render, override `rescale` / `colormap_name`, or (on
`raw` only) choose their own `variables` / `assets`. The website uses `raw`
for everything, so its [render specs](/guide/glossary#render-spec) and
colorbars stay the single source of colors.
:::
