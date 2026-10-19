# Evaluation: a persistent cache of rendered tiles

Question: should every tile, once rendered, be stored in our own storage
and served from there afterwards, instead of being re-rendered by the
tiler Lambda whenever CloudFront doesn't have it? How much better than
CloudFront alone would that be, what would it cost, and how should it be
stored?

Short answer: it would remove almost every re-render after the first, so
revisits cost ~0.1 s instead of 1-25 s. At this project's traffic it costs
cents and saves cents: the gain is latency. Most of the cost and transfer
saving comes from changing *what* is cached (512 px rendered images of
50-600 KB instead of 2-3 MB raw arrays), not from where. Recommended:
first make CloudFront keep fixed-time tiles for a year and add Origin
Shield (configuration only); if revisits still miss, add an S3 tile store
behind CloudFront as the primary origin with the tiler as failover.

## What happens today (measured 2026-10-19, dev deployment)

The website asks the tiler for each dataset's `raw` render as a 512 x 512
`.npy` array and colors it in the browser. CloudFront caches responses by
full URL: 1 day for fixed times, 60 s for "latest" (the origin's
`Cache-Control`; [cache policy](./cloudfront#cache-policy)).

| Request (from New Haven) | Render (CloudFront miss) | CloudFront hit | Size |
|---|---|---|---|
| GOES-19 LST, raw `.npy`, 512 px | 2.1 s | 0.78 s | 3.1 MB |
| ERA5-Land, raw `.npy`, 512 px | 1.5 s | 0.38 s | 2.1 MB |
| CHIRPS, raw `.npy`, 512 px | 0.5 s | 0.36 s | 2.1 MB |
| HLS true color PNG, 256 px | 2.3-22.6 s (first: 504) | | 150 KB |
| HLS NDVI PNG, 256 px | 7.8 s | 0.19 s | 143 KB |
| NISAR balanced PNG, 256 px | 6.8 s | 0.18 s | 211 KB |
| SMAP PNG, 256 px | 24.5 s | 0.10 s | 2 KB |
| GOES true color PNG, 256 px | 9.2 s | 0.33 s | 7 KB |
| ERA5-Land PNG, 256 px | 3.3 s | 0.13 s | 1.5 KB |
| ASTER PNG, 256 px | 1.0 s | 0.16 s | 61 KB |
| Black Marble PNG, 256 px | 5.4 s | 0.12 s | 17 KB |

(Before the [lookup cache](./lookup-cache); CMR search is part of the NASA
renders.) A CloudFront hit is ~0.1-0.3 s for small tiles and ~0.4-0.8 s for
the 2-3 MB arrays, most of it transfer. A render is 0.5-25 s.

CloudFront misses an already-rendered tile when:

1. **the TTL ran out**: fixed-time tiles are kept 1 day;
2. **it was evicted**: CloudFront drops rarely requested objects from an
   edge location, with no guarantee of how long they stay (for a
   low-traffic site, often days);
3. **another edge asks**: each edge location and each of the ~13 regional
   edge caches has its own copy, so a tile rendered for a viewer in Boston
   is rendered again for one in Frankfurt.

## The proposal

Key each fixed-time tile by its canonical request (dataset, render,
resolved time, tile matrix, z/x/y, scale, format, the remaining
parameters). The first request renders it and stores it; every later
request, from any edge, reads it from the store. "Latest" requests (GOES
without a time) are not stored.

### What to store: raw arrays or rendered images

| | Raw `.npy` (what the website fetches now) | Rendered RGB(A) image, WebP or PNG |
|---|---|---|
| Size, 512 px | 2-3 MB (float32, plus mask) | WebP 30-150 KB, PNG 100-600 KB for imagery; 2-60 KB for colormapped fields |
| One response serves | every product of the dataset (the browser colors each) | one product (render spec) |
| Coloring | browser (`colorize` in `tiles.js`) | tiler, from the same render spec: the tiler presets already have the renders; the website's specs would have to become tiler parameters |
| Storage per 1 million tiles | ~2.5 TB ($58/month in S3 Standard) | ~100 GB ($2.30/month) |
| Transfer per 1,000 tiles | ~2.5 GB | ~0.1 GB |

The website's colors are fixed per product (there is no interactive
rescaling), so the browser doesn't need the raw values to draw the map.
Rendering on the server means each product of a dataset is cached
separately (HLS true color, CIR and NDVI from the same bands are three
images, today one array), but each is ~20x smaller. Storing images also
matches the question asked: "the RGB image as rendered by the browser".

### Cost per 1,000 tiles

List prices (us-east-1 / us-west-2, 2026), 512 px tiles, before free tiers:

| | Re-render on Lambda | From an S3 tile store |
|---|---|---|
| Compute | NASA deployment (2.9 GB, arm64) x ~5 s: $0.20; NOAA / ECMWF (2 GB) x ~1.5 s: $0.04 | none if CloudFront reads S3 directly; ~$0.002 if a Lambda checks S3 first |
| Requests | API Gateway $0.001, Lambda $0.0002 | S3 GET $0.0004 (PUT $0.005 once per tile) |
| Source reads | NASA / NOAA buckets in-region: free; ECMWF and CHC over the internet | none |
| Storage | none | $0.023 per GB-month |
| CloudFront to viewers | $0.085 per GB (raw: $0.21; images: $0.01) | the same |

At this project's traffic everything fits in the free tiers (CloudFront:
1 TB and 10 million requests a month; Lambda: 400,000 GB-s a month), so
the monthly bill is ~$0 either way. As an example at 50,000 tiles a month
with 10,000 new ones, past the free tiers: today ~$6 of renders plus ~$11
of transfer for raw arrays; with an image store ~$2 of renders, ~$0.10 of
S3 and ~$0.40 of transfer.

### Latency

| Path | Typical |
|---|---|
| CloudFront hit | 10-50 ms at the edge, plus transfer |
| CloudFront miss, S3 origin hit | + 30-80 ms |
| CloudFront miss, Lambda checks S3 (warm) | + 50-150 ms (API Gateway, Lambda, S3 GET); + 0.5-1.5 s on a SnapStart restore |
| CloudFront miss, render | 0.5-25 s |

So against CloudFront alone, the store changes cases 1-3 above from
0.5-25 s to ~0.1-0.2 s. When CloudFront already has the tile, it changes
nothing.

## Store options

| Option | Read path | Latency on a CloudFront miss | Cost | Notes |
|---|---|---|---|---|
| **S3 Standard, one object per tile, as CloudFront's primary origin** (recommended) | CloudFront -> S3; on 403/404 the origin group fails over to the tiler, which renders, writes the object and responds | +30-80 ms | $0.023/GB-month, $0.0004 per 1,000 GETs, $0.005 per 1,000 PUTs | No Lambda on hits. A CloudFront Function maps the URL to an S3 key (a hash of the canonical query) and passes the original URL in a header for the tiler. Lifecycle rules expire tiles by prefix (e.g. after 90 days) |
| S3 Standard, Lambda checks first | CloudFront -> tiler -> S3 GET, else render | +50-150 ms, more on restores | adds ~$2 per million hits of Lambda time | Simplest code (in `PresetMiddleware`), but every hit runs a Lambda |
| S3 Express One Zone | Lambda -> directory bucket | +15-30 ms warm | $0.11/GB-month (5x), cheaper requests | Single-AZ; not usable as a CloudFront S3 origin to my knowledge, so a Lambda is in the path anyway, which erases its latency edge |
| DynamoDB, binary attribute | Lambda -> GetItem | +50-150 ms (through the Lambda) | $0.25/GB-month (10x S3); a 100 KB read is 13-25 read units (~$1.5-3 per million) | 400 KB item limit: no raw arrays, large PNGs don't fit. No advantage over S3 for blobs |
| ElastiCache (Valkey) | Lambda in a VPC -> cache | +5-10 ms after the Lambda | memory-priced (~$90/month per 10 GB serverless), plus a NAT gateway (~$32/month) | Fastest store, but memory is the wrong price for a cold archive |
| PMTiles / MBTiles archive per dataset, render and time | the browser reads byte ranges of one file through CloudFront | like a CloudFront hit, no Lambda | S3 storage only | Immutable: the pyramid must be rendered ahead of time over a fixed extent (Greater New Haven, zoom 8-16: ~800 tiles at 512 px, 50-300 MB). Good for pre-built and static layers (ASTER, CT impervious surface), not for any time on demand |

Key layout for the S3 options:
`tiles/{dataset}/{render}/{time}/{tms}/{z}/{x}/{y}{@scale}.{format}/{hash of the other parameters}`.
The dataset and time prefixes make it easy to delete a dataset or time
(for example when the lookup cache's prune job finds its granules
changed), and spread requests across prefixes.

## Cheaper first step: let CloudFront keep tiles

Fixed-time tiles never change (the URL pins the time; granules are fixed
once settled), so the origin could send `Cache-Control: public,
max-age=31536000, immutable` for them instead of 1 day; the cache policy
already allows up to a year. Adding **Origin Shield** (one extra caching
layer in front of each origin, ~$0.009 per 10,000 requests that reach it)
makes every edge location share one copy, which removes case 3 and most of
case 1. Eviction (case 2) remains: CloudFront doesn't promise to keep
anything. Both are a few lines in `settings.py` and `cloudfront.tf`.

## Recommendation

1. Long `Cache-Control` for fixed-time preset responses, and Origin
   Shield. Measure the CloudFront hit rate (CloudFront's cache statistics)
   for a few weeks.
2. If revisits still miss, add the S3 tile store as CloudFront's primary
   origin with the tiler as failover, storing rendered images.
3. Independently, consider moving the website to server-rendered WebP for
   tiler datasets: ~20x less transfer, browser memory and cache storage,
   at the price of one cached image per product instead of one array per
   dataset.

The [Icechunk evaluation](./icechunk-evaluation) compares this with
caching the data instead of the images.
