# CloudFront (`cloudfront.tf`)

One distribution gives the tiler a single URL, caches rendered tiles at the
edge, and routes each request to the region that serves it.

## Routes from the catalog {#routes-from-the-catalog}

::: code-group
<<< @/../terraform/tiler/cloudfront.tf#routes [cloudfront.tf#routes]
:::

`yamldecode` reads the same `datasets.yaml` as the app. Each dataset
becomes a path pattern `/datasets/{id}/*` to the origin named by its
`deployment`; `/cmr/*` (raw titiler-cmr) goes to the NASA region.
Everything else goes to the NOAA region: `/datasets` and `/datasets/{id}`
(catalog metadata, which any region can serve), `/xarray`, `/cog`,
`/healthz`.

::: warning Design decision: one source of truth for routing
Hand-written routes would let a dataset added in the wrong place silently
go to a region that is slow for it or lacks its credentials. Generated
routes declare the region once, next to the dataset. CloudFront allows 25
cache behaviors per distribution by default; there are 10.
:::

The plan test asserts the generated table:

::: code-group
<<< @/../terraform/tiler/tests/plan.tftest.hcl#routes-assert [tests/plan.tftest.hcl#routes-assert]
:::

## Passing on the viewer's host

::: code-group
<<< @/../terraform/tiler/cloudfront.tf#viewer-host [cloudfront.tf#viewer-host]
:::

The origin request policy (`Managed-AllViewerExceptHostHeader`) forwards
all viewer headers, cookies and query strings *except* `Host`, because API
Gateway routes by its own hostname. This viewer-request function copies the
viewer's `Host` into `X-YCGS-Host` first, and the app restores it
([EdgeMiddleware](./app#edgemiddleware)), so TileJSON URLs point at
CloudFront.

## Cache policy {#cache-policy}

::: code-group
<<< @/../terraform/tiler/cloudfront.tf#cache-policy [cloudfront.tf#cache-policy]
:::

::: warning Design decision: the origin decides how long; the whole query string is the key
- **Cache key.** Every query parameter changes the image (time, rescale,
  overrides), so the whole query string is in the key; cookies are not.
  `Origin` is added only when CORS is restricted, because CORS headers then
  differ per origin.
- **TTLs.** Minimum 0 and maximum a year, so the origin's `Cache-Control`
  decides: a year for settled fixed times (`s-maxage`, which CloudFront
  uses over `max-age`), 1 day for recent fixed times, 60 s for "latest"
  ([caching](./requests#caching)). The 1-hour default applies only when the
  origin sends none.
- **Compression.** gzip / brotli in the key lets CloudFront store
  compressed JSON (and NPY).

The preset layer's [parameter allowlist](./requests#what-a-client-may-change)
keeps the key from growing with irrelevant parameters.
:::

## Origins {#origins}

::: code-group
<<< @/../terraform/tiler/cloudfront.tf#origins [cloudfront.tf#origins]
:::

Each origin is reached over HTTPS only, with a 30 s read timeout (the
Lambda and API Gateway limit), and gets the `X-Origin-Verify` header,
which CloudFront overwrites if a viewer sends one.

**Origin Shield** (`origin_shield`, on by default) adds one shared cache
layer in front of each origin, in its region (or the nearest region that
has Origin Shield: `us-west-1` uses `us-west-2`, `eu-south-1` uses
`eu-central-1`). Without it every regional edge cache that misses asks
the tiler, so a tile is rendered once per region its viewers are in; with
it they all fill from the shield's copy. It costs ~$0.0075 (US) to
~$0.009 (EU) per 10,000 requests that reach it, and a CloudFront
invalidation clears it like the rest of the cache.

::: code-group
<<< @/../terraform/tiler/tests/plan.tftest.hcl#origin-shield-assert [tests/plan.tftest.hcl#origin-shield-assert]
:::

## Behaviors and errors

::: code-group
<<< @/../terraform/tiler/cloudfront.tf#behaviors [cloudfront.tf#behaviors]
<<< @/../terraform/tiler/cloudfront.tf#error-caching [cloudfront.tf#error-caching]
:::

Only `GET`, `HEAD` and `OPTIONS` are allowed, so titiler's `POST`
endpoints (statistics over a GeoJSON feature) are not reachable through
CloudFront: the public surface is cacheable reads. The rest is standard:
redirect to HTTPS, HTTP/2 and 3, IPv6, the default `*.cloudfront.net`
certificate, no geo restriction.

CloudFront caches error responses for 10 s by default. A minimum of 0 for
5xx means a tile that timed out once (e.g. on a cold start) is retried on
the next request.
