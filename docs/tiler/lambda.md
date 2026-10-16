# Lambda handler and image (`handler.py`, `Dockerfile`)

`ycgs_titiler.handler.handler` is the function Lambda calls (the image's
`CMD`). Everything else in the module runs once, at initialization, which
SnapStart snapshots.

```mermaid
sequenceDiagram
  participant T as tofu apply
  participant L as Lambda service
  participant I as Init (handler.py import)
  participant R as Restored environment
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
they hold connections that were open at snapshot time. boto3 reconnects by
itself. The `ImportError` branch keeps the module importable outside Lambda.

::: warning Design decision: a container image with SnapStart
Upstream titiler and titiler-cmr deploy zip packages, which to fit Lambda's
250 MB limit compile a minimal GDAL, build packages from source and strip
`.py` files and most of botocore. This image uses standard wheels (10 GB
limit) and still gets SnapStart, which AWS supports for images built on the
Lambda Python 3.12+ base images. SnapStart replaces the multi-second import
of the geospatial stack with a snapshot restore. Points to check:

- **Cost.** Python SnapStart is billed per cached snapshot (per published
  version, while it exists) and per restore. The module deletes all but the
  newest 3 versions after each deploy
  ([version pruning](./infrastructure#version-pruning)).
- **Uniqueness.** Anything random created at init is shared by all restored
  environments. Nothing here generates secrets or IDs at init.
- **Init time.** Init plus snapshot must finish within the publish timeout.
:::

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
