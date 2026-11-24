# Lambda handler and packaging (`handler.py`, `lambda_entry.py`, `Dockerfile`)

The tiler is deployed as a **zip package on Lambda's managed Python 3.14
runtime** (`packaging = "zip"`, the default; [why](#zip-package)), or as a
container image (`packaging = "image"`). `ycgs_titiler.lambda_entry.handler`
(zip) or `ycgs_titiler.handler.handler` (image `CMD`) is the function Lambda
calls; everything else in `handler.py` runs once, at initialization.
SnapStart can snapshot that init (`snap_start`), but is **off by default**:
the zip package initializes in a predictable few seconds (importing the
app; nothing is unpacked), and a snapshot is billed around the clock.

```mermaid
sequenceDiagram
  participant T as tofu apply
  participant L as Lambda service
  participant I as Init (handler.py import)
  participant R as Restored environment
  Note over T,R: with SnapStart on (snap_start = true; off by default)
  T->>L: new image or environment: publish version N
  L->>I: run init once
  I->>I: read secrets (Secrets Manager)
  I->>I: import titiler, GDAL, PROJ; load datasets.yaml; build app + middleware
  I-->>L: memory snapshot of version N
  T->>L: point alias "live" at version N
  Note over L,R: later, for each new execution environment
  L->>R: restore from the snapshot (no imports)
  R->>R: after-restore hook: clear dataset and listing caches
  R->>R: serve requests (Mangum → FastAPI)
```

## Secrets at initialization

::: code-group
<<< @/../tiler/src/ycgs_titiler/handler.py#load-secrets [handler.py#load-secrets]
:::

Each secret is a JSON object whose keys become environment variables: the
Earthdata secret sets `TITILER_CMR_EARTHDATA_USERNAME` and `..._PASSWORD`,
the CDS secret `YCGS_CDS_API_KEY`. This runs *before* the app is imported,
because titiler-cmr reads its settings at import. Null values are skipped:
OpenTofu writes nulls when the secret variables were not given
([secrets](./infrastructure#secrets)).

::: warning Design decision: read secrets once, at init
Reading on every request costs latency and API calls; the Parameters and
Secrets Lambda Extension is another moving part. With SnapStart the values
are part of the encrypted snapshot, so a new secret value only takes effect
in a new published version. The module forces that by putting the secret's
version ID in the function's environment (`YCGS_SECRET_VERSION`).
:::

## Pre-warming <Badge type="tip" text="standard" />

::: code-group
<<< @/../tiler/src/ycgs_titiler/handler.py#prewarm [handler.py#prewarm]
:::

Importing the app already loads FastAPI, titiler, xarray, rasterio (GDAL)
and pyproj and validates `datasets.yaml`. This block also builds
Starlette's middleware stack (otherwise built on the first request), enters
a GDAL environment and loads the PROJ database, as titiler-cmr's own
handler does. `Mangum(app, lifespan="off")` is the standard titiler Lambda
adapter; `text_mime_types` lists the responses that are text (others, like
PNG, are base64-encoded for API Gateway).

## SnapStart hooks

::: code-group
<<< @/../tiler/src/ycgs_titiler/handler.py#snapstart-hooks [handler.py#snapstart-hooks]
:::

`snapshot_restore_py` ships with the Lambda Python base images and runs
registered functions after a restore. Ours empties the open-dataset and
small-variable caches, the GOES listing caches and the obstore clients:
they hold connections that were open at snapshot time. It also makes the
[lookup cache](./lookup-cache) create its DynamoDB client anew
(`lookups.reset()`). boto3 reconnects by itself. The `ImportError` branch
keeps the module importable outside Lambda.

::: info Earlier design: a container image with SnapStart
Upstream titiler and titiler-cmr deploy zip packages, which to fit Lambda's
250 MB limit compile a minimal GDAL, build packages from source and strip
`.py` files and most of botocore. This image uses standard wheels (10 GB
limit) and still gets SnapStart, which AWS supports for images built on the
Lambda Python 3.12+ base images. SnapStart replaces the multi-second import
of the geospatial stack with a snapshot restore. Points to check:

- **Cost.** Python SnapStart is billed per restore and per cached snapshot:
  each published version, while it exists, around the clock whether it is
  invoked or not (memory × ~$0.0000015 per GB-s, ~$8/month for 2 GB). The
  module deletes all but the live version after each deploy
  (`keep_versions`, default 1;
  [version pruning](./infrastructure#version-pruning)). For a deployment
  that is rarely used, `snap_start` (`tiler_snap_start` in
  `terraform/complete`) turns SnapStart off: no snapshot to pay for, and
  every cold start runs the multi-second init.
- **Uniqueness.** Anything random created at init is shared by all restored
  environments. Nothing here generates secrets or IDs at init.
- **Init time.** Init plus snapshot must finish within the publish timeout.
:::

## Zip package

::: code-group
<<< @/../tiler/Dockerfile#zip{dockerfile} [Dockerfile#zip]
<<< @/../tiler/src/ycgs_titiler/lambda_entry.py [lambda_entry.py]
:::

`docker buildx build --target zip --output type=local,dest=DIR` writes
`DIR/tiler.zip` (`tiler/package/slim.py`): **207 MB unpacked** on x86_64,
an estimated 218-224 MB on arm64, whose wheels align their segments to 64 KB
(Lambda's limit for a zip is 250 MB); 75 MB zipped. It runs as it is:
nothing is unpacked at init.

- **Bytecode only** (hash-based `.pyc`, no sources), no tests, stubs or C
  sources; **boto3/botocore left out** (the runtime has them).
- **numpy built without BLAS/LAPACK.** The wheel bundles OpenBLAS and
  gfortran (~25 MB); the tiler does no linear algebra. Built from the
  locked version's source (`-Dallow-noblas=true`); two minutes, cached.
- **Shared objects stripped** (`strip --strip-unneeded`): most wheels ship
  debug symbols, about 70 MB of the stack. A stripped file whose segments
  the loader would refuse keeps its symbols (binutils breaks libraries
  auditwheel already patched, such as numpy's OpenBLAS).
- **One copy of the PROJ data:** rasterio's `proj.db` is pyproj's (same
  PROJ version, same contents); `lambda_entry` points `PROJ_DATA` at
  pyproj's.
- **What the tiler never loads is left out** (`tiler/package/trim.txt`):
  cramjam, Pillow's AVIF/FreeType/LCMS/WebP plugins and their libraries,
  numpy's test modules and f2py, extension modules built for other Python
  versions. Found with an import trace over every dataset preset.
- **`libexpat` in `lib/`** (rasterio needs it; the runtime lacks it;
  `/var/task/lib` is on the runtime's library path).
- **Checked in a clean runtime image** (`zipcheck` stage): every shared
  object loads and the handler imports, or the build fails. `slim.py` also
  fails the build over 250 MB.
- **Byte-identical across builds:** sorted entries, fixed timestamps.

`slim.py --tarball` still builds the earlier layout (dependencies as
`deps.tar.zst`, unpacked to `/tmp` at init by `lambda_entry`; needs
`ephemeral_storage_mb = 1024`), should the stack outgrow 250 MB.

::: warning Design decision: trim the wheels and rebuild numpy, not GDAL
How far each change gets, measured locally (x86_64) against a snapshot of
every preset's data ([report](./package-size-evaluation)):

| Package | Unpacked | Cold start, init |
|---|---|---|
| dependencies in `deps.tar.zst` (before) | 325 MB in `/tmp` | unpack 1.2 s + import 2.5 s |
| wheels trimmed (strip, PROJ data, trim.txt) | 231 MB | import only |
| + one copy of libraries several wheels bundle (patchelf) | 218 MB | import only |
| + numpy without BLAS | 194 MB | import only |
| + GDAL and PROJ from source, only the drivers used | 179 MB | import only |
| **trimmed wheels + numpy without BLAS** (this build) | **207 MB** | import only |

Every one of them gives byte-identical tiles. The chosen build is the
smallest change with room to spare (17 % under the limit): trimming alone
leaves 8 %, and the further steps cost more than they save. Sharing
libraries between wheels means rewriting their ELF headers, and only works
where the copies match symbol for symbol (rasterio's PROJ renames its
symbols, so it can't replace pyproj's). A GDAL build is a 20-minute
compile whose versions must follow rasterio's.
:::

The module builds it once (`terraform_data.zip`, like the image build: needs
docker with buildx) and each regional deployment uploads it to its own
`<name>-code-<region>` bucket (zips over 50 MB deploy from S3) under a key
with the content hash, so new code deploys only when the app changes.

::: warning Design decision: a zip on the managed runtime, SnapStart off
With container images and SnapStart off, a cold start's cost depends on
whether Lambda still has the image cached. Right after a deploy, or after a
quiet spell (five idle days were enough), init ran past Lambda's 10 s init limit: Lambda then initializes
again inside the request, and API Gateway's 30 s limit turned some first
requests into 503s. After an hour or two of traffic, cold starts took
3.5-4.5 s. (Importing the app takes 0.5 s on a warm disk; the rest is
loading the ~1 GB image lazily: 10,600 files, of which init reads ~3,400
Python files and ~190 shared libraries.) The managed runtime is cached on
every Lambda host and the zip arrives in one piece, so the zip's init is the
same in both cases:

| Forced cold start (three regions) | Image, just deployed | Image, after use | Image, after 5 idle days | Zip (any of the three) |
|---|---|---|---|---|
| Init phase | over 10 s (timeout) | within the limit | 10 s timeouts in 5 of 9 functions | 2.9-5 s: unpack 1.4-2.7 s†, import 1.5-3.0 s |
| First request (`/healthz`) | 4 s to a 503 at 30 s | 3.5-4.5 s | 5-31 s, 3 of 9 were 503s | not measured alone |
| First tile | 10-30 s, some 503s | 3.6-11 s | | 6.7-20 s* |

\*Measured in the ycgs-tiler benchmarks (`ycgs-tiler/06-slim`) behind a
router Lambda: these times include the router's own cold start (about 1 s)
and an Invoke hop, which this module doesn't have.
†The zip measured then unpacked its dependencies to `/tmp`; the current
package fits unpacked and skips that step.

The zip trades a warm image cache's best case (about 1-2 s slower to the
first tile) for never hitting the init limit, which matters for a lightly
used site that is redeployed with every change. `packaging = "image"` keeps
images. With SnapStart off there is no snapshot to pay for (~$8/month per
2 GB version); `snap_start` still turns it on per deployment.
:::

The dependencies also lost titiler.xarray's `fs` extra (s3fs, gcsfs and the
Google Cloud stack, grpc, aiohttp: 65 MB never imported; the readers use
obstore).

## The image

`tiler/pyproject.toml` pins the libraries and `uv.lock` every transitive
version. titiler-cmr is not on PyPI, so it is a git dependency on a tag.

::: code-group
<<< @/../tiler/pyproject.toml [pyproject.toml]
<<< @/../tiler/Dockerfile#builder{dockerfile} [Dockerfile#builder]
<<< @/../tiler/Dockerfile#final{dockerfile} [Dockerfile#final]
:::

- **Builder on the runtime base image,** so compiled wheels match the
  runtime. `uv export --frozen` turns the lockfile into a pinned
  requirements list, installed into a plain directory with bytecode
  compiled; tests and type stubs are deleted.
- **Two packages the base image lacks:** `findutils` (no `find` command),
  and `libexpat`, which the rasterio wheel links against (upstream titiler
  copies it too).
- **Import check as the last build step** (`from ycgs_titiler.handler
  import handler`): a broken import or an invalid `datasets.yaml` fails the
  build, not the deploy.

The same package also runs the [lookup cache](./lookup-cache)'s weekly prune
job: a second function in the NASA and NOAA deployments with the handler
`ycgs_titiler.lambda_entry.prune` (zip) or the command
`ycgs_titiler.prune.handler` (image, `image_config`), without SnapStart.

::: warning Design decision: Python 3.14 on arm64
Python 3.14 is the newest generally available Lambda Python runtime, and
every binary dependency has 3.14 wheels for arm64. The speed gain over
3.12 is small (tiles spend their time in C libraries and network reads).
arm64 Lambda costs less per GB-second and builds natively on Apple
Silicon. `image_platform = "linux/amd64"` switches; the module derives the
Lambda architecture from it.
:::

Lambda accepts only single-platform image manifests, and buildx adds
provenance and SBOM attestations by default (an image *index*), so the
build uses `--provenance=false --sbom=false`
([image build](./infrastructure#image-build-inside-tofu-apply)).
