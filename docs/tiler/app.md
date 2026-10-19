# Application (`main.py`, `settings.py`)

`main.py` builds one FastAPI app: our backends and preset routes, titiler's
standard routers, titiler-cmr mounted in the NASA region, and the
middleware stack. The same image runs in all three regions; environment
variables set by OpenTofu decide what each copy does:

| Variable | nasa | noaa | ecmwf |
|---|---|---|---|
| `YCGS_FEATURES` | `cmr` (mount titiler-cmr) | – | – |
| `YCGS_SECRET_ARNS` | Earthdata secret | – | CDS secret |
| `TITILER_CMR_EARTHDATA_S3_DIRECT_ACCESS` | `TRUE` | – | – |
| `YCGS_ORIGIN_VERIFY` | shared CloudFront secret | same | same |

titiler-cmr is not even imported outside the NASA region.

## Settings <Badge type="tip" text="standard" />

[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
reads `YCGS_*` environment variables. The defaults suit local runs: no
origin check, CORS open, no CMR.

::: code-group
<<< @/../tiler/src/ycgs_titiler/settings.py#settings [settings.py#settings]
:::

## The app

::: code-group
<<< @/../tiler/src/ycgs_titiler/main.py#create-app [main.py#create-app]
:::

- **Exception mapping:** 403 for a URL outside the allowlist, 503 for
  missing credentials, 404 for a missing variable, 400 for an unparseable
  time. Otherwise all would be 500s, which CloudFront treats alike.
- **Backends** `/xarray` and `/cog` (below), and **`/datasets`**: the preset
  metadata routes (data routes are rewritten by the middleware).
- **Tiling schemes and colormaps:** titiler's standard routers.
- **`/cmr`:** mounted only with the `cmr` feature. Without Earthdata
  credentials, a stub that always answers 503 is mounted instead.
- **`/healthz`** (region and features) and a landing JSON at `/`.

::: warning Design decision: a 503 stub instead of failing startup
titiler-cmr's settings require an Earthdata username and password at
import. If the secret is empty (a first deploy without the `TF_VAR_*`
values), importing it would crash initialization, which with SnapStart
happens when the version is *published*, so `tofu apply` would fail. The
stub keeps the rest of the service working and says what is missing.
:::

## Backends

`/xarray` is titiler.xarray's `TilerFactory` with
[`MultiVarReader`](./readers#the-reader-class). `MultiVarParams` declares
its query parameters with titiler-cmr's names: `variables` (repeatable),
`sel`, `group`, `decode_times` and `expression`.

`/cog` is titiler.core's standard COG `TilerFactory` (rio-tiler and GDAL),
whose `url` parameter goes through the [URL allowlist](./readers#the-url-allowlist)
first. It serves the CHIRPS preset.

::: code-group
<<< @/../tiler/src/ycgs_titiler/main.py#multivar-params [main.py#multivar-params]
<<< @/../tiler/src/ycgs_titiler/main.py#cog-path [main.py#cog-path]
:::

## Middleware order

::: code-group
<<< @/../tiler/src/ycgs_titiler/main.py#middleware-order [main.py#middleware-order]
:::

Starlette runs middleware in reverse order of addition, so a request passes
`EdgeMiddleware`, then CORS, `PresetMiddleware`, titiler's
`CacheControlMiddleware`, and the router. The CloudFront check comes first,
so nothing else runs for rejected requests. CORS comes before the preset
rewrite, so the errors `PresetMiddleware` sends itself (unknown dataset or
render, a parameter that isn't allowed, a missing `datetime2`, no scan near
the time) carry CORS headers and a browser can read their JSON `detail`.
CORS doesn't depend on the path, so the rewrite doesn't affect it. The
preset rewrite comes before routing, and outside `CacheControlMiddleware`,
so its Cache-Control replaces the generic 1-hour value for preset
responses. CORS (`*` by default, `GET` only) and the cache-control
middleware are titiler's standard setup.

## EdgeMiddleware

::: code-group
<<< @/../tiler/src/ycgs_titiler/main.py#edge-middleware [main.py#edge-middleware]
:::

1. **Origin check.** CloudFront adds `X-Origin-Verify: <secret>` to every
   request it forwards ([CloudFront](./cloudfront#origins)). Requests
   without it, e.g. straight to the API Gateway URL, get 403.
   `hmac.compare_digest` avoids leaking the secret through timing.
2. **Public host.** CloudFront must send API Gateway its own hostname as
   `Host`. A CloudFront Function copies the viewer's `Host` to
   `X-YCGS-Host`, and this middleware puts it back, so URLs the app builds
   (TileJSON) point at CloudFront.

::: warning Design decision: a shared secret instead of an authorizer
The data are public; the point is to keep traffic, and cost, behind
CloudFront's cache. A Lambda authorizer costs an invocation per uncached
request; AWS WAF a fixed monthly fee. Lambda function URLs with CloudFront
Origin Access Control would drop API Gateway, worth considering later, but
give up its per-stage throttling and access logs. The secret is in OpenTofu
state and the Lambda environment; leaking it only allows bypassing the
cache. `X-YCGS-Host` is a custom name because CloudFront restricts which
headers functions may set; it is only trusted when the secret matched.
:::

## Mounting titiler-cmr

::: code-group
<<< @/../tiler/src/ycgs_titiler/main.py#cmr-app [main.py#cmr-app]
:::

titiler-cmr's whole app is mounted under `/cmr`, with its routes, OpenAPI
docs and middleware as upstream wrote them, plus:

- **An extra factory at `/xarray-grouped`**: titiler-cmr's
  `CMRTilerFactory` with `GroupedXarrayGranuleReader`
  ([fixes](./fixes#grouped-hdf5)) and the dependencies of titiler-cmr's own
  `/xarray`. A flag on the app state keeps it from being registered twice
  when the app is built twice (tests).
- **`startup()` called directly.** titiler-cmr creates its CMR client and
  Earthdata authentication in a FastAPI *lifespan* handler. Mangum runs
  with lifespans off, and mounted sub-apps get no lifespan events anyway;
  titiler-cmr's own Lambda handler does the same.

At the end of the module the catalog is loaded and the app built, both at
import: that is what SnapStart snapshots and what the image build checks.

## Tests

`test_app.py` builds the whole app with a one-dataset catalog (a synthetic
ERA5-like Zarr) and the CloudFront secret set, and exercises it through
FastAPI's `TestClient`: Cache-Control and time headers, uncached errors,
point values of a two-time difference, TileJSON with the CloudFront host,
`/times`, `/xarray` with two variables, and the titiler-cmr mount with the
grouped backend.

::: code-group
<<< @/../tiler/tests/test_app.py#origin-verify [test_app.py#origin-verify]
:::
