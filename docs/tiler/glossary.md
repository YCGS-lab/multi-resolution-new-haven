# Tiler glossary

Terms used in the tiler pages, beyond the [main glossary](/guide/glossary)
(COG, CRS, granule, tile, Web Mercator, ...).

## Data and formats

### NetCDF / HDF5 {#netcdf-hdf5}
Self-describing file formats for multidimensional arrays (e.g. time × y × x)
with named variables, dimensions, groups and attributes. NetCDF-4 is a
convention on top of [HDF5](https://www.hdfgroup.org/solutions/hdf5/).

### HDF-EOS5 {#hdf-eos5}
NASA's HDF5 profile for Earth-observing products. Grid metadata sit in a text
block (`StructMetadata`) and data under `HDFEOS/GRIDS/<grid>/Data Fields`;
some products, such as Black Marble, also store 1-D `lat` / `lon` arrays.

### Zarr {#zarr}
A cloud-native format for chunked, compressed N-dimensional arrays, each
chunk a separate object ([zarr.dev](https://zarr.dev)). A reader fetches only
the chunks it needs.

### Chunk {#chunk}
The unit an array is split into for storage and compression. Reading any
value in a chunk reads the whole chunk. A *time-chunked* store holds a short
time span over a large area per chunk (good for maps); a *geo-chunked* store
a long time series over a small area.

### ARCO {#arco}
"Analysis-Ready, Cloud-Optimized": data re-packaged (here as Zarr) so it can
be read directly from object storage. ECMWF publishes ERA5-Land this way.

### CF conventions, grid mapping {#cf}
The [Climate and Forecast conventions](https://cfconventions.org/) for
NetCDF metadata. A *grid mapping* variable describes the projection of the
x/y coordinates; pyproj turns it into a CRS (`CRS.from_cf`).

## Data sources

### CMR {#cmr}
NASA's [Common Metadata Repository](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html),
the search catalog for all Earthdata collections and granules. A
*collection concept ID* (e.g. `C2854338529-ASF`) identifies a collection;
`temporal` filters granules by time (ranges are inclusive).

### Earthdata Cloud and direct S3 access {#earthdata-cloud}
NASA stores most data in S3 in **us-west-2**. Code running in us-west-2 can
read it directly with temporary S3 credentials from the data centre's
`s3credentials` endpoint. Elsewhere, reads go through HTTPS URLs that
redirect through Earthdata Login. An
[Earthdata Login](https://urs.earthdata.nasa.gov/) account is needed either way.

### DAAC {#daac}
Distributed Active Archive Center: a NASA data centre. Here: ASF (NISAR),
NSIDC (SMAP), LP DAAC (HLS, ASTER), LAADS (Black Marble).

### CDS {#cds}
The Copernicus [Climate Data Store](https://cds.climate.copernicus.eu/), run
by ECMWF. Its ARCO Zarr stores at `arco.datastores.ecmwf.int` are read with
an API key as a bearer token.

### GOES ABI, fixed grid {#goes-abi}
The Advanced Baseline Imager on NOAA's geostationary GOES satellites. Its
products are published to the public S3 bucket `noaa-goes19`, one NetCDF
file per product and scan ([NOAA Open Data](https://registry.opendata.aws/noaa-goes/)).
The files store x/y as scan angles (radians) seen from the satellite, the
*fixed grid*; multiplied by the satellite height they become meters in the
geostationary projection.

## Tiling

### TMS, TileJSON {#tilejson}
A tile matrix set (TMS) defines a tile grid; `WebMercatorQuad` is the
standard Web Mercator one. [TileJSON](https://github.com/mapbox/tilejson-spec)
is a small JSON document giving a map client the tile URL template, zoom
range and bounds of a layer.

### titiler, rio-tiler {#titiler}
[titiler](https://developmentseed.org/titiler/) is a FastAPI framework for
dynamic tiling. Its *factories* create sets of endpoints (tiles, TileJSON,
bbox, point, info) around a *reader* class from
[rio-tiler](https://cogeotiff.github.io/rio-tiler/). Band math is an
*expression* over bands `b1`, `b2`, ..., with `;` between output bands.

### titiler-cmr {#titiler-cmr}
A titiler application ([repo](https://github.com/developmentseed/titiler-cmr))
that searches CMR for granules and renders them with an xarray backend
(NetCDF / HDF5) or a rasterio backend (COGs), mosaicking the granules found.

### xarray, lazy loading, `sel` {#xarray}
[xarray](https://docs.xarray.dev/) is the Python library for labelled
multidimensional arrays. Opening is *lazy*: only metadata are read until
values are needed, and `.sel(time=...)` on a lazy array only narrows what
will be read. titiler.xarray exposes it as `sel={dim}={value}` or
`sel={dim}={method}::{value}` (e.g. `nearest`).

### obstore {#obstore}
A fast Python client for S3, HTTP and local object storage
([docs](https://developmentseed.org/obstore/)), used to read Zarr chunks and
byte ranges of NetCDF files.

## Web and AWS

### ASGI, middleware {#asgi}
[ASGI](https://asgi.readthedocs.io/) is the interface between Python web
servers and async apps (FastAPI, Starlette). A *middleware* wraps the app
and sees every request and response; the request is a dictionary, the
*scope*, holding the path and query string.

### Mangum {#mangum}
An adapter ([docs](https://mangum.fastapiexpert.com/)) that turns an API
Gateway event into an ASGI request, and the response back.

### Lambda version and alias {#lambda-version}
*Publishing* a Lambda function creates an immutable numbered version. An
*alias* (here `live`) is a named pointer to one version.

### SnapStart {#snapstart}
[Lambda SnapStart](https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html)
runs the initialization once when a version is published, snapshots the
memory, and starts new environments from the snapshot. For Python it is
billed per cached snapshot and per restore.

### API Gateway HTTP API {#api-gateway}
The [HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html)
flavour of API Gateway: a public HTTPS endpoint forwarding to a Lambda.
Integrations time out after 30 s.

### CloudFront behavior, cache key, function {#cloudfront}
In [CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html),
a *cache behavior* routes a path pattern to an *origin*; the *cache key* is
the part of a request that identifies a cached response; a *CloudFront
Function* is a small JavaScript function run at the edge on each request.

### ECR, Secrets Manager {#ecr}
[ECR](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html)
is AWS's container registry; Lambda only runs images from ECR in its own
region. [Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
stores versioned secrets.

## OpenTofu

### Provider alias, `configuration_aliases` {#provider-alias}
A second configuration of a provider, here one AWS provider per region. A
module declares the aliases it expects with `configuration_aliases`; the
caller passes them in (`providers = { aws.nasa = aws.nasa, ... }`).

### Ephemeral variable, write-only attribute {#ephemeral}
OpenTofu ≥ 1.11 can mark a variable `ephemeral`: its value is never saved in
state or plan files. It can only flow into *write-only* arguments (e.g.
`secret_string_wo`), which the provider sends but does not store. See the
[OpenTofu docs](https://opentofu.org/docs/language/ephemerality/).

### `terraform_data` and `local-exec` {#local-exec}
`terraform_data` is a built-in resource with no remote object. Its
`local-exec` provisioner runs a shell command on the machine running `tofu`
when the resource is created or replaced.
