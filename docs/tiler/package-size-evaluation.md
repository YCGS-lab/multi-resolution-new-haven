# Evaluation: the zip package under 250 MB

Question: the tiler's dependencies were ~325 MB, over the 250 MB Lambda
allows for an unzipped package, so the zip carried them as `deps.tar.zst` and
unpacked them to `/tmp` on every cold start (1.4-2.7 s on Lambda). Can the
package fit unpacked, and what does each way of shrinking it cost? Ideas
considered: building GDAL and PROJ from source, sharing the native libraries
the wheels bundle, a package per deployment, splitting the functions by
reader type, and Rust (GDAL bindings or terrio) or C++ instead of Python.

Short answer: the standard wheels fit after trimming. The chosen zip
(`tiler/Dockerfile`, `zip` target):

- has its symbols stripped, one copy of the PROJ data, and what the tiler
  never loads left out;
- has numpy built without BLAS.

It is **207 MB unpacked on x86_64** (an estimated 218-224 MB on arm64),
with **byte-identical tiles** and **cold starts ~1 s faster** (no unpack).
Building GDAL from source or sharing libraries between wheels gets lower
(179 and 218 MB), but costs more than it saves. Splitting the functions
doesn't shrink the largest one. Rust and C++ weren't needed.

::: tip Status
The trimmed zip is built and the default ([zip package](./lambda#zip-package)).
The other variants, the benchmark harness and the opt-in "reader" layout
described below are on the branch `claude/tiler-lambda-size-9hiq1d`
([`tiler/experiments/lambda-size`](https://github.com/YCGS-lab/multi-resolution-new-haven/tree/claude/tiler-lambda-size-9hiq1d/tiler/experiments/lambda-size),
with the full report), not merged.
:::

## How it was measured (2026-11-24, locally)

- **Data:** a recorded snapshot of everything the tiler reads (34 GB, mostly
  the seven NISAR GCOV granules of 2026-07-17 that the overview tiles
  touch). A mitmproxy addon recorded every HTTPS read once, fetching each
  object whole, then replayed it offline with byte ranges, so every variant
  read the same bytes.
- **Requests:** 174, covering all 10 presets at their default times (GOES
  pinned), 4 zoom levels over the New Haven AOI, a styled render (PNG) and
  `raw` (`.npy`) each.
- **Runtime:** each package unpacked as `/var/task` in
  `public.ecr.aws/lambda/python:3.14`, invoked through its Runtime Interface
  Emulator with API Gateway v2 events. One function per deployment, with
  its production memory and CPU in proportion (1 vCPU per 1769 MB), and the
  module's GDAL settings.
- **Measured:**
  - 10 cold starts per function, each after dropping the page cache;
  - two warm passes over the request set;
  - peak resident memory;
  - every response compared with the `deps.tar.zst` package's.
- **Platform:** x86_64 (Lambda runs arm64: see [arm64](#arm64)).

## Where the size went

| MB | What |
|---:|---|
| 66 | `rasterio.libs`: GDAL with all its drivers, HDF5, netCDF, GEOS, sqlite, OpenSSL, PROJ, ... |
| 49 | `rasterio`: extension modules with debug symbols (7 once stripped), PROJ data 10 |
| 26 | `numpy.libs`: OpenBLAS and gfortran |
| 26 | pandas (xarray needs it) |
| 33 | pyproj and `pyproj.libs` (PROJ data again, a second PROJ, curl, sqlite) |
| 15 | obstore |
| 19 | Pillow and `pillow.libs` (AVIF, FreeType, HarfBuzz, ...) |
| 16 | h5py and `h5py.libs` (a second HDF5) |

Debug symbols were the largest single item: stripping alone took 324 MB to
256 MB. Libraries bundled twice (PROJ, HDF5, GEOS, sqlite, curl, ...)
account for only 22 MB.

## Variants

Each builds on the one before; all gave byte-identical responses (174/174).

| Variant | Unpacked (x86_64) | Cold start: init / first tile* | Cost |
|---|---:|---|---|
| `deps.tar.zst`, unpacked at init (before) | ~325 MB in `/tmp` | 3.6 s (unpack 1.2) / 5.1 s | – |
| V1: trim the wheels: strip, one PROJ data, `tiler/package/trim.txt` | 231 MB | 2.8 s / 4.2 s | `slim.py` options |
| V2: + one copy of each library several wheels bundle, re-linked with patchelf | 218 MB | 2.8 s / 4.2 s | ELF rewriting |
| V3: + numpy without BLAS | 194 MB | 2.6 s / 4.0 s | a 2-minute cached build |
| V4: + GDAL 3.12.2 and PROJ 9.8.1 from source, only GTiff/COG, MEM, VRT, PNG, JPEG, WEBP and curl | 179 MB | 2.7 s / 4.0 s | a 20-minute build tracking rasterio's versions; JPEG 2000 output lost |
| **Chosen: V1 + numpy without BLAS** | **207 MB** (75 MB zipped) | **2.6 s / 3.9 s** | |

\*Median over the three functions' cold starts; warm latency (p50 ~0.1 s
from the snapshot) and peak memory were the same for all.

V1 alone leaves 8 % headroom on x86_64 and ~3 % on arm64; the chosen build
leaves 17 % (x86_64). The chosen build stops before V2 and V4:

- **V2** has to rewrite ELF headers. A matching version isn't enough:
  rasterio's wheel renames PROJ's symbols (`internal_proj_*`), so its PROJ
  can't stand in for pyproj's.
- **V4** builds GDAL in about 20 minutes, and its versions must follow
  rasterio's.

## A package per deployment, a function per reader type

**V5, one package per deployment.** With the app importing only the
backends each deployment serves:

| Deployment | Package |
|---|---|
| ecmwf | 212 MB |
| noaa | 224 MB |
| nasa | still the whole stack: titiler-cmr needs everything |

**V6, one function per deployment and reader type.** Cloud-Optimized
GeoTIFF datasets and xarray datasets go to separate functions, all behind
the one CloudFront distribution:

| Path | Function |
|---|---|
| `/cmr/rasterio/*` | nasa-raster (HLS, ASTER) |
| `/cmr/*` | nasa (NISAR, SMAP, Black Marble, VIIRS LST) |
| `/cog/*` | noaa-raster (CHIRPS) |
| `/datasets/{id}/*` | from `datasets.yaml`: the raster function if the backend is `cog` or `cmr-rasterio`, else the deployment's |
| default (catalog, `/xarray/*`, docs, TMS, colormaps) | noaa (GOES) |

ecmwf has only xarray datasets and stays one function. Each function would
get `YCGS_BACKENDS` and import only its readers. The raster function shares
its deployment's lookup cache table. Tile URLs and cache keys don't change.

Findings:

- **Size.** rio-tiler warps and encodes every tile with GDAL, so the xarray
  functions need rasterio as well as xarray, pandas, h5py and zarr. Only the
  CHIRPS function gets small: 152 MB, or 100 MB with V4. The NASA xarray
  function stays at the full size, so splitting doesn't help the limit.
- **Cold starts.** Smaller imports start faster (init 1.1-2.1 s for the
  smaller functions), but there are more functions to start. A visitor
  moving from HLS to SMAP starts two NASA functions instead of one.
- **Operations.** Memory, concurrency and SnapStart become per function; the
  cost guard and outputs must list all five.

When it makes sense: to give COG tiles (0.5 GB peak) and xarray tiles
different memory or concurrency. It is not a way to save package size.

## NISAR needs more than 3008 MB

The nasa function peaked at **~4.0-4.3 GB** over two passes in every
variant, the `deps.tar.zst` package included. At its production 3008 MB it
was killed (out of memory) on repeated low-zoom NISAR tiles. Those tiles
(z6, the preset's minimum) mosaic up to 7 GCOV granules, and titiler-cmr
reads them at full resolution: the HDF5 files have no overviews. The fix,
not made here, is more `lambda_memory` for nasa, a higher NISAR `minzoom`,
or reading less per tile. noaa peaked at 0.5 GB and ecmwf at 1.0 GB.

## arm64

Lambda runs these functions on arm64, but QEMU couldn't be set up in the
test environment, so nothing was built or run for arm64. Instead:

- The locked arm64 wheels were trimmed the same way. Use GNU strip for
  this: `llvm-strip` breaks auditwheel-patched files on arm64.
- **V1 on arm64 is 242 MB** (x86_64: 231). arm64 wheels align segments to
  64 KB, which pads every extension module.
- With numpy rebuilt without BLAS, the chosen build should be
  **~218-224 MB** on arm64.

`slim.py` fails the build over 250 MB, so check
`docker buildx build --platform linux/arm64 --target zip` before deploying.
V2's re-linking would take off another ~13 MB if needed.

## Other findings

- **Stripping can break libraries auditwheel has already patched.**
  binutils left numpy's OpenBLAS and gfortran unloadable. `slim.py` checks
  each stripped file's segment alignment and keeps the original if needed;
  the `zipcheck` build stage loads every shared object.
- **titiler-cmr's rasterio reader sends no credentials over HTTPS.**
  Production reads through `/vsis3` with in-region credentials, so this
  only matters outside us-west-2.
- **rasterio sets `GDAL_CURL_CA_BUNDLE` to certifi's bundle.** It takes
  precedence over `CURL_CA_BUNDLE`, which matters with a custom CA.
- **`tiler/package/` wasn't in the package's content hash,** so a
  `slim.py` change alone didn't rebuild the zip. It is in the hash now.

## Not tried

- **Rust (GDAL bindings or terrio) and C++ with GDAL,** since the Python
  stack fits. For the record, terrio (0.9, "early development") reads COG,
  NetCDF/HDF5 and Zarr in pure Rust. Its Rust API has windowed reads but no
  warp, and it has no HDF-EOS support.
- **Deploying.** The local cold starts compare variants; they don't predict
  Lambda's times, which add fetching the zip and starting the runtime.
