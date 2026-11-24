# The tiler's zip package under 250 MB, without unpacking at init

**Question.** PR #6 deploys the tiler as a zip on Lambda's managed Python 3.14
runtime. Its dependencies come to about 325 MB, over the 250 MB Lambda allows
for an unzipped package, so they ship as `deps.tar.zst` and are unpacked to
`/tmp` on every cold start (1.4-2.7 s on Lambda). Can the package fit
unpacked, and at what cost?

**Answer.** Yes, without leaving the standard wheels. The new `zip` target
(`tiler/Dockerfile`) has three parts:

- the wheels trimmed: symbols stripped, one copy of the PROJ data, and what
  the tiler never loads (`package/trim.txt`) left out;
- numpy built without BLAS;
- no unpack step.

Its size:

| | Unzipped | Zipped | Under the 250 MB limit |
|---|---|---|---|
| x86_64 (measured) | 207.4 MB | 75.4 MB | 17 % |
| arm64 (estimated, see [arm64](#arm64)) | about 218-224 MB | – | 10-13 % |

Measured locally on x86_64 against a snapshot of every dataset preset's
data, it gives **byte-identical tiles** to PR #6 (174 of 174 responses). It
**starts about 1.1 s sooner** (init 2.6 s instead of 3.7 s), with the same
warm latency and memory.

Changes that go further (sharing native libraries between wheels, building
GDAL and PROJ from source) get to 194 and 179 MB, also with identical
output. They cost more than they save. Splitting the functions per
deployment (V5) or per reader type (V6) doesn't shrink the largest
function, because the NASA xarray function needs nearly everything.

The Rust (GDAL bindings, terrio) and C++ options were not tried in this
round: the Python stack fits.

## How it was measured

- **Data.** `snapshot/snapshot_proxy.py`, a mitmproxy addon, records every
  HTTPS read the tiler makes and replays it offline. Objects are fetched
  whole once and served with byte ranges; API responses are stored as
  they are. The snapshot is 34 GB, mostly the 7 NISAR GCOV granules of
  2026-07-17 that the overview tiles touch.
- **Requests.** 174 in all (`bench/requests.py`): all 10 presets at their
  default times (GOES pinned to 2026-11-20 17:01 UTC), 4 zoom levels from
  the preset's minimum over the New Haven AOI, up to 6 tiles per zoom.
  Each in the first styled render (PNG) and `raw` (`.npy`), plus GOES
  `red-500m` and `ir-clean` and ERA5 `diff`.
- **Runtime.** Each package unpacked as a read-only `/var/task` in
  `public.ecr.aws/lambda/python:3.14`, invoked through its Runtime
  Interface Emulator with API Gateway v2 events. There is one function per
  deployment, each with its production memory (nasa 3008 MB, noaa and
  ecmwf 2048 MB) and CPU in proportion (1 vCPU per 1769 MB). The nasa
  containers' memory cap was raised to 4096 MB; see
  [NISAR memory](#nisar-needs-more-than-3008-mb). The production GDAL
  settings (`gdal_env`) were used.
- **Cold starts.** 10 per function (5 for V5 and V6), each a fresh container
  after dropping the page cache: init from `lambda_entry`'s log line, and
  the first tile's time.
- **Warm latency.** The whole request set twice. Pass 1 asks for each tile
  for the first time (datasets opened on first use); pass 2 repeats it.
- **Peak memory.** Peak resident memory (`VmHWM`) of the function's Python
  process, after two passes with an 8 GB cap.
- **Output.** Every response compared with P0's (`bench/compare.py`): `.npy`
  arrays and decoded PNG pixels.
- **Platform.** x86_64 (this machine). Lambda runs arm64: see
  [arm64](#arm64).

## Where the size goes (P0, x86_64)

325 MB unpacked, of which 127 MB are extension modules and bundled
libraries:

| MB | What |
|---:|---|
| 66 | `rasterio.libs`: GDAL (28) with all its drivers, HDF5, netCDF, GEOS, sqlite, OpenSSL, PROJ, ... |
| 49 | `rasterio`: extension modules with debug symbols (stripped: 7), PROJ data 10 |
| 26 | `numpy.libs`: OpenBLAS 23, gfortran 3 |
| 26 | pandas (xarray needs it) |
| 20 + 13 | pyproj (PROJ data 10), `pyproj.libs` (a second PROJ, curl, sqlite) |
| 15 | obstore |
| 13 + 6 | `pillow.libs` (AVIF, FreeType, HarfBuzz, ...), PIL |
| 10 + 6 | h5py, `h5py.libs` (a second HDF5) |
| 6 | `shapely.libs` (a second GEOS) |

Several of these libraries ship in two copies (PROJ, HDF5, GEOS, sqlite,
curl, libtiff, ...), but that accounts for only 22 MB. Debug symbols were
the largest single item: stripping alone takes 324 MB to 256 MB.

## Variants, from the smallest change to the largest

V1-V4 build on each other (`variants/variants.Dockerfile`). V5 and V6 change the
deployment, and were measured on top of V1 and on top of V4.

| | Change | Effort and risk |
|---|---|---|
| V1 | Same wheels. `strip --strip-unneeded` on every shared object, one copy of the PROJ data (rasterio's `proj.db` is the same as pyproj's), and what the request set never loads left out (`package/trim.txt`). | `slim.py` options and a list. Stripping is checked: a stripped file whose LOAD segments the loader would refuse keeps its symbols (binutils damages numpy's OpenBLAS, which auditwheel had patched). |
| V2 | + one copy of each library that several wheels bundle, re-linked with patchelf (`variants/dedupe.py`): GEOS, curl, libtiff, libpng, WebP, zstd, ... | ELF rewriting. Same version isn't enough: rasterio's PROJ renames its symbols (`internal_proj_*`), so it can't replace pyproj's. `dedupe.py` merges only when the kept copy exports every symbol. |
| V3 | + numpy built from source without BLAS/LAPACK (`-Dallow-noblas=true`) | A 2-minute cached build. numpy without BLAS is slower only at linear algebra, which the tiler doesn't do. |
| V4 | + PROJ 9.8.1 and GDAL 3.12.2 built from source with only GTiff/COG, MEM, VRT, PNG, JPEG, WEBP and curl. rasterio and pyproj are built against them. | A 20-minute build whose versions must follow rasterio's. Loses GDAL's other drivers (JPEG 2000 output, for example). |
| V5 | One package per deployment (`variants/fn_package.py`). The app imports only the backends it serves (`YCGS_BACKENDS`). | Three zips. |
| V6 | One function per deployment and reader type (COG vs xarray), routed by CloudFront | Two more functions; see [V6](#v6-one-function-per-reader-type). |
| **Chosen** | **V1 + V3's numpy**, without V2's re-linking | `tiler/Dockerfile` `zip` target |

### Size (x86_64)

| Variant | Unzipped MB | Zipped MB | Under the 250 MB limit |
|---|---:|---:|---:|
| P0: PR #6 (deps.tar.zst, unpacked at init) | 91.1 zipped as is; **~325 after unpacking** | 90.9 | – |
| V1: trim the wheels | 230.9 | 81.9 | 8% |
| V2: + one copy of shared libraries | 217.5 | 77.2 | 13% |
| V3: + numpy without BLAS | 193.9 | 70.7 | 22% |
| V4: + GDAL/PROJ from source | 179.0 | 65.1 | 28% |
| **Chosen: V1 + numpy without BLAS** | **207.4** | **75.4** | **17%** |

| Function package (V5, V6) | on V1: unzipped MB | on V4: unzipped MB |
|---|---:|---:|
| V5 nasa | 230.9 | 179.0 |
| V5 noaa | 224.2 | 172.3 |
| V5 ecmwf | 212.4 | 160.4 |
| V6 nasa-raster | 230.8 | 178.8 |
| V6 nasa-xarray | 230.9 | 179.0 |
| V6 noaa-raster | 152.0 | 100.0 |
| V6 noaa-xarray | 224.2 | 172.3 |
| V6 ecmwf-xarray | 212.4 | 160.4 |

### Output

Every variant's 174 responses are **byte-identical** to P0's: V1-V4, V5 and
V6 on both bases, and the chosen build. V4 too, because it builds the same
GDAL and PROJ versions as the wheels bundle.

### Cold starts and latency (x86_64, local)

Medians of 10 cold starts per function (5 for V5 and V6). For each function
the first tile is HLS (nasa), GOES ABI true color (noaa) or ERA5 (ecmwf).
For V6 it is SMAP for nasa-xarray, which reads a whole SMAP granule (hence
its 6.7 s), and CHIRPS for noaa-raster.

| Variant | Function | Init s (unpack + import) | First tile s | Warm pass 1 p50 / p95 s | Pass 2 p50 / p95 s | OK |
|---|---|---:|---:|---:|---:|---:|
| p0 | nasa | 3.78 (1.22 + 2.57) | 5.25 | 0.128 / 1.690 | 0.124 / 1.167 | 240/240 |
| p0 | noaa | 3.57 (1.10 + 2.47) | 5.10 | 0.124 / 0.655 | 0.120 / 0.274 | 84/84 |
| p0 | ecmwf | 3.64 (1.19 + 2.45) | 4.13 | 0.118 / 0.177 | 0.117 / 0.134 | 24/24 |
| v1 | nasa | 2.78 | 4.22 | 0.108 / 1.492 | 0.111 / 1.105 | 240/240 |
| v1 | noaa | 2.77 | 4.34 | 0.130 / 0.599 | 0.114 / 0.242 | 84/84 |
| v1 | ecmwf | 2.92 | 3.49 | 0.114 / 0.158 | 0.119 / 0.133 | 24/24 |
| v2 | nasa | 2.81 | 4.23 | 0.121 / 1.562 | 0.108 / 1.115 | 240/240 |
| v2 | noaa | 2.76 | 4.32 | 0.107 / 0.601 | 0.114 / 0.274 | 84/84 |
| v2 | ecmwf | 2.72 | 3.25 | 0.111 / 0.140 | 0.102 / 0.109 | 24/24 |
| v3 | nasa | 2.64 | 4.00 | 0.117 / 1.508 | 0.106 / 1.410 | 239/240* |
| v3 | noaa | 2.52 | 4.02 | 0.109 / 0.583 | 0.110 / 0.220 | 84/84 |
| v3 | ecmwf | 2.67 | 3.20 | 0.108 / 0.165 | 0.112 / 0.142 | 24/24 |
| v4 | nasa | 2.62 | 3.99 | 0.119 / 1.507 | 0.112 / 1.251 | 240/240 |
| v4 | noaa | 2.69 | 4.08 | 0.115 / 0.450 | 0.110 / 0.240 | 84/84 |
| v4 | ecmwf | 2.70 | 3.22 | 0.117 / 0.181 | 0.105 / 0.124 | 24/24 |
| v5-v1 | nasa | 2.77 | 4.04 | 0.117 / 1.625 | 0.108 / 1.097 | 240/240 |
| v5-v1 | noaa | 2.11 | 3.67 | 0.117 / 0.619 | 0.121 / 0.262 | 84/84 |
| v5-v1 | ecmwf | 2.11 | 2.64 | 0.121 / 0.175 | 0.113 / 0.149 | 24/24 |
| v5-v4 | nasa | 2.55 | 3.90 | 0.119 / 1.507 | 0.108 / 1.217 | 240/240 |
| v5-v4 | noaa | 1.98 | 3.38 | 0.112 / 0.410 | 0.108 / 0.263 | 84/84 |
| v5-v4 | ecmwf | 1.89 | 2.41 | 0.116 / 0.176 | 0.108 / 0.121 | 24/24 |
| v6-v1 | nasa-xarray | 2.45 | 6.70 | 0.114 / 2.608 | 0.105 / 1.381 | 128/128 |
| v6-v1 | nasa-raster | 2.48 | 3.60 | 0.112 / 0.325 | 0.101 / 0.243 | 112/112 |
| v6-v1 | noaa-xarray | 1.83 | 3.38 | 0.113 / 0.519 | 0.107 / 0.222 | 68/68 |
| v6-v1 | noaa-raster | 1.25 | 1.60 | 0.025 / 1.177 | 0.029 / 0.040 | 16/16 |
| v6-v1 | ecmwf-xarray | 1.93 | 2.50 | 0.104 / 0.159 | 0.100 / 0.120 | 24/24 |
| v6-v4 | nasa-xarray | 2.36 | 6.79 | 0.114 / 2.300 | 0.102 / 2.247 | 127/128* |
| v6-v4 | nasa-raster | 2.37 | 3.53 | 0.110 / 0.297 | 0.103 / 0.259 | 112/112 |
| v6-v4 | noaa-xarray | 1.74 | 3.24 | 0.105 / 0.384 | 0.108 / 0.223 | 68/68 |
| v6-v4 | noaa-raster | 1.11 | 1.46 | 0.025 / 1.085 | 0.023 / 0.044 | 16/16 |
| v6-v4 | ecmwf-xarray | 1.79 | 2.29 | 0.107 / 0.161 | 0.100 / 0.107 | 24/24 |
| **chosen** | nasa | **2.64** | **4.00** | 0.115 / 1.341 | 0.103 / 1.023 | 240/240 |
| **chosen** | noaa | **2.46** | **3.92** | 0.108 / 0.582 | 0.102 / 0.244 | 84/84 |
| **chosen** | ecmwf | **2.64** | **3.14** | 0.108 / 0.149 | 0.109 / 0.121 | 24/24 |

\*The NISAR z6 tile ran out of memory on the second pass, even under a
4096 MB cap; see the next section.

- **Unpacking cost P0 1.1-1.2 s per cold start** here, a local disk. On
  Lambda it measured 1.4-2.7 s (PR #6). Every variant skips it.
- **Import time** follows how much is imported, not package size: 2.5-2.9 s
  with the whole app. In V5 and V6 a function imports only its own
  backends: 1.8-2.1 s for the xarray functions without titiler-cmr, 1.1-1.3 s
  for CHIRPS alone.
- **Warm latency** is the same everywhere, within noise (p50 about 0.1 s
  from the local snapshot). Neither numpy without BLAS nor the source-built
  GDAL is slower.

## NISAR needs more than 3008 MB

The local containers measured this; it was not checked on AWS.

| Variant | nasa peak MB (setting 3008) | noaa peak MB (2048) | ecmwf peak MB (2048) |
|---|---:|---:|---:|
| p0 | 4050 | 520 | 1080 |
| v1 | 4234 | 505 | 1003 |
| v2 | 4000 | 506 | 1023 |
| v3 | 4325 | 506 | 976 |
| v4 | 4027 | 484 | 1024 |
| chosen | 4018 | 493 | 969 |

The nasa function peaks at about 4 GB in every variant, **PR #6 included**.
With nasa's production 3008 MB it is killed (out of memory) on the second
pass over the NISAR tiles, in P0 too. The low-zoom NISAR tiles (z6, the
preset's minimum) mosaic up to 7 GCOV granules, and titiler-cmr's xarray
reader reads them at full resolution: these HDF5 files have no overviews.
The packaging changes don't affect it. Raising nasa's `lambda_memory` or
NISAR's `minzoom` would. It isn't changed here.

## arm64

Lambda runs these functions on arm64 (`image_platform = "linux/arm64"`).
Registering QEMU to build and run arm64 images here needed a privileged
container, which wasn't permitted, so **nothing was built or run on arm64**.
The sizes were estimated instead:

- The locked arm64 wheels were downloaded (`uv pip install
  --python-platform aarch64-manylinux_2_28`) and V1 applied to them. They
  were stripped with GNU binutils 2.42 for aarch64; the build image has
  2.39. LLVM's `llvm-strip` breaks auditwheel-patched files on arm64,
  moving their appended segments off their 64 KB alignment; GNU strip
  doesn't.
- Result: **V1 on arm64 is 242.3 MB** (x86_64: 230.9). arm64 wheels align
  segments to 64 KB, which pads every extension module: h5py +5.5 MB,
  pandas +3.2, rasterio +2.6, pyproj +2.4. Their numpy is smaller.
- **The chosen build on arm64:** V1 without numpy's wheel files (13.5 + 24.3
  MB), plus a source-built numpy of 13.5-19 MB, gives **about 218-224 MB**,
  10-13 % under the limit. The source-built numpy is 19.0 MB on x86_64,
  2.7 MB more than the wheel's numpy, hence the range.

`slim.py` fails the build above 250 MB, so a real arm64 build can't silently
exceed it. Run `docker buildx build --platform linux/arm64 --target zip`
(native on Apple Silicon) before deploying. If it lands closer to the limit
than estimated, V2's re-linking would take off another ~13 MB.

## V6: one function per reader type

`function_layout = "reader"` (terraform, opt-in) puts each deployment's COG
datasets in a second function behind the same CloudFront distribution:

| Path | Origin |
|---|---|
| `/cmr/rasterio/*` | nasa_raster |
| `/cmr/*` | nasa |
| `/cog/*` | noaa_raster |
| `/datasets/{id}/*` | `{deployment}_raster` if the preset's backend is `cog` or `cmr-rasterio` and the deployment has xarray datasets too, else `{deployment}` |
| default (catalog, `/xarray/*`, `/api.html`, TMS, colormaps) | noaa |

Five functions: nasa (xarray), nasa_raster, noaa (xarray, also the default
route), noaa_raster, and ecmwf (xarray only, not split). Each gets
`YCGS_BACKENDS` and imports only its readers. A preset request for the other
type gets a 404, which CloudFront never sends there. The raster function
shares its deployment's DynamoDB lookup table. `tofu test` checks the route
table and the five origins (`run "reader_layout"`).

Implications:

- **Size.** It doesn't help where it's needed. rio-tiler warps and encodes
  every tile with GDAL, so the xarray functions need rasterio as well as
  xarray/pandas/h5py/zarr. The NASA xarray function needs titiler-cmr as
  well, which needs everything. Only the CHIRPS function gets small (152 MB
  on V1, 100 MB on V4). Every function therefore deploys the same zip.
- **Cold starts.** Smaller imports start faster (above), but there are more
  functions to start. A visitor moving from HLS to SMAP starts two NASA
  functions instead of one, and warm instances are shared by fewer
  datasets.
- **Operations.** Memory, concurrency and SnapStart become per function
  (`nasa_raster` / `noaa_raster` keys). The cost guard and outputs list all
  five. `/api.html` at the default route documents only the noaa xarray
  function's endpoints.
- **Use** it to give the COG and xarray readers different memory or
  concurrency (COG tiles need far less: noaa peaks at 0.5 GB). Don't use it
  to save package size.

## Other findings

- **Stripping is the cheapest large saving** (~70 MB), but binutils can
  damage libraries auditwheel already patched. Two came out unloadable on
  x86_64: numpy's OpenBLAS and gfortran. `slim.py` now checks each stripped
  file's segment alignment and keeps the original where it would break; the
  `zipcheck` build stage loads every shared object in a clean runtime.
- **rasterio's and pyproj's PROJ are not interchangeable** despite the same
  version: rasterio renames PROJ's symbols. Their `proj.db` files are the
  same, so only the data is shared.
- **titiler-cmr's rasterio reader sends no credentials over HTTPS.**
  Production reads Earthdata Cloud through `/vsis3` with in-region S3
  credentials, so this only matters outside us-west-2. The snapshot proxy
  added the token itself while recording.
- **rasterio sets `GDAL_CURL_CA_BUNDLE` to certifi's bundle**, which takes
  precedence over `CURL_CA_BUNDLE`. That matters only with a custom CA, as
  here.
- **The PR's `image_tag` hash didn't include `tiler/package/`**, so a change
  to `slim.py` alone wouldn't rebuild the zip. It now does.
- **`ephemeral_storage_mb`** goes back to 512 MB: nothing is unpacked.

## Not done

- Rust (GDAL bindings, terrio), C++ with GDAL: not pursued this round, since
  the Python stack fits. For the record, terrio (0.9, "early development")
  reads COG, NetCDF/HDF5 and Zarr in pure Rust. Its Rust API has windowed
  reads but no warp, and there is no HDF-EOS support.
- Nothing was deployed. Cold starts on Lambda add fetching the zip and
  starting the runtime; the local numbers compare variants, they don't
  predict Lambda's.
- arm64: estimated, not built (above).
