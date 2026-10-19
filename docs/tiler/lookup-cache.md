# Lookup cache (`lookups.py`, `granules.py`, `prune.py`)

Some requests wait on a lookup before they can read any pixels: which
granules cover this tile (a CMR search), or which GOES scan is nearest to
this time (an S3 listing). The lookup cache stores those answers in a
DynamoDB table per regional deployment, so a later request, in any
execution environment, reads the answer back instead of asking again. A
weekly job deletes entries that have expired or are no longer correct.

This page starts with the evaluation done before building it (what is
slow, the expected benefit and cost, the storage options), then describes
what was built.

## What is slow (measured 2026-10-19)

From a laptop in New Haven: 6 identical requests per case, one z12 tile
over New Haven, as titiler-cmr issues them (`granules.umm_json`, page size
20).

| Lookup | Median | Min | Max | Notes |
|---|---|---|---|---|
| CMR, HLS L30, one day | 2.0 s | 0.13 s | 18.6 s | 1 granule |
| CMR, NISAR GCOV, one day | 4.3 s | 0.16 s | 23.6 s | 1 granule |
| CMR, SMAP L4, one instant | 3.4 s | 0.17 s | 16.3 s | |
| CMR, VIIRS LST, one day | 0.16 s | 0.12 s | 2.9 s | |
| CMR, Black Marble, one year | 0.30 s | 0.15 s | 1.2 s | plus one 30 s timeout |
| CMR, ASTER GDEM (static) | 0.16 s | 0.12 s | 4.9 s | |
| S3 list, GOES MCMIPC hour | 50 ms | 45 ms | 224 ms | 12 keys |
| S3 list, GOES CMIPC hour | 64 ms | 60 ms | 120 ms | 192 keys |

CMR's floor is ~0.13 s, but the same query often takes several seconds and
sometimes 15-25 s, and one timed out at 30 s, which is also the Lambda and
API Gateway limit: that tile fails. The variance is on CMR's side, so a
Lambda in us-west-2 sees the same. GOES listings are fast and already
cached per execution environment (`timeres._list_complete_hour`).

## Where the time goes today

titiler-cmr searches CMR **once per tile request** (and per point or bbox
request), for the granules intersecting that tile. CloudFront caches the
rendered tile by URL, so the search is repeated whenever the URL is new:

- another tile of the same image (panning, zooming);
- another render of the same granules (HLS true color, CIR, NDVI; the six
  NISAR composites): a different URL, the same search;
- the same view a day later (CloudFront's 1-day TTL) or from another
  edge location.

## Design: one search per parent tile

Caching each tile's search would only help the exact same tile. Instead
the cache key is the search (collection, time filter, other CMR
parameters) plus the **parent tile**: the Web Mercator tile at zoom 8
(~120 x 90 km at New Haven) containing the request. Greater New Haven is
in one or two zoom-8 tiles, so every tile of a view from zoom 8 to 16
shares one entry. The parent search returns a few granules (HLS: 4,
NISAR: 2, SMAP: 1, ASTER: 6 for one day over New Haven), and each request
picks its own from that list locally, as titiler-cmr would: in CMR order,
the granules intersecting it, stopping once it is covered.

That gives the same answer as the per-tile search because the parent
search stops only once the parent is covered: the request's granules are
the ones, in the same order, intersecting the request, and the request is
covered no later than its parent. Checked against live CMR for HLS, NISAR,
SMAP and ASTER at zooms 10, 12 and 13: identical granules in all 12 cases.
If the parent list was cut off at 200 granules before the request was
covered, the request runs its own search.

## Predicted benefit

| Situation | Today | With the cache |
|---|---|---|
| First view of a dataset and time in an area | one CMR search per tile, all in parallel | the same (every tile misses at once), plus ~10 ms for the cache read and write |
| More tiles of that image (pan, zoom) | one CMR search per new tile | cache read (~5-10 ms); saves 0.15-4 s per tile, 15-25 s in the tail |
| Another render of the same granules | one CMR search per tile | cache read |
| Same view later, another user or edge | one CMR search per tile | cache read, for 90 days for settled times |
| CMR slow or down | tiles time out (504) | tiles already looked up still work |
| GOES scan for a time | ~50 ms listing per hour, per new execution environment (usually 1-3 per time) | ~5-10 ms read; saves ~50-150 ms on cold environments only |

For NISAR, whose tiles take ~5-10 s, the median search (~4 s) is a large
part of a tile; for HLS and SMAP about 2-3 s; for VIIRS LST, Black Marble
and ASTER little in the median, but the tail is removed for all of them.
The first view of a new date doesn't get faster: its tiles are requested
together and all miss. GOES gains little; it shares the mechanism because
it is a few lines.

## Cost

| | Estimate |
|---|---|
| DynamoDB reads | $0.125 per million read units; an entry is 1-10 KB compressed (1-3 units): ~$0.0003 per 1,000 tile requests |
| DynamoDB writes | $0.625 per million write units; ~5 units per new entry: ~$0.003 per 1,000 new entries |
| DynamoDB storage | $0.25 per GB-month (the first 25 GB are free); 10,000 entries x 5 KB = 50 MB |
| Prune job | one Lambda run a week, 1 GB, minutes: under $0.01 a month |
| EventBridge Scheduler | free tier (14 million invocations a month) |
| Lambda time saved | the NASA function (2.9 GB, arm64) costs $0.039 per 1,000 seconds-of-waiting; at 2 s saved per hit, ~$0.08 per 1,000 hits |

At this project's traffic the cache costs cents a month and saves about as
much in Lambda time: the gain is latency and reliability, not money.

Complexity: three small modules (~350 lines with tests), one table, one
scheduled function per region. The only coupling to titiler-cmr is
subclassing its `CMRBackend` (set as each factory's `backend`). A cache
failure is logged and the request searches CMR as before.

## Storage options

| Option | Lookup latency (in region) | Writes on a miss | Expiry | Cost at this scale | Fit |
|---|---|---|---|---|---|
| **DynamoDB, one item per lookup** (built) | 3-10 ms | one `PutItem` | native TTL attribute | cents | Best: key-value access is exactly what it does; no new dependency (boto3) |
| S3 Standard, one JSON object per lookup | 20-60 ms first byte | one `PUT` ($5 per million) | lifecycle rule by prefix (e.g. `ttl=90d/`) | cents | Good second choice: no new service, but slower reads and 10x the request price |
| S3 Express One Zone, one object per lookup | 5-10 ms | one `PUT` | none (job must delete) | ~$0.11 per GB-month, cheaper requests | Fast, but single-AZ, a directory bucket per region and per-AZ placement: more setup for a cache this small |
| Parquet files in S3, read with DuckDB / pyarrow | 50-300 ms (footer, then row group) | append a new small file; a job compacts | job rewrites the files | cents | Poor: every miss writes a file, point lookups scan files, needs compaction and a new dependency |
| S3 Tables (managed Iceberg) | 100-500 ms (metadata JSON, manifest list, manifest, data file) | an Iceberg commit per miss; concurrent commits conflict | Iceberg deletes + compaction | storage $0.0265/GB, plus compaction and per-object monitoring | Poor: built for analytics scans, not single-key lookups; PyIceberg in the image |
| ElastiCache (Valkey) serverless | <1 ms | `SET` with TTL | native | from ~$6/month, plus the Lambda in a VPC needs a NAT gateway (~$32/month) to reach CMR | Overkill: the fastest, but a VPC for a public-data tiler |

Parquet and S3 Tables would make sense for *analysing* the lookups (which
granules users look at), not for answering them; DynamoDB can export to
S3 if that is wanted later.

## Measured after deployment (dev, 2026-10-19)

256 px PNG tiles over New Haven, each a CloudFront miss, in order:

| Request | Before (no lookup cache) | With it |
|---|---|---|
| HLS, first tile of a date (parent search) | 2.3-22.6 s, one 504 | 504 (CMR timed out after titiler-cmr's 20 s), then 17.4 s (two CMR pages) |
| HLS, other tiles and renders in the same parent | 7.8 s | 0.92 s, 0.82 s |
| NISAR, first tile of a date | 6.8 s | 4.7 s |
| NISAR, other tiles and renders | | 1.5 s, 3.2 s |

The logs show no CMR query for the later tiles: "reading Tile" follows
"opening data" by 12 ms. The prune job's first run recomputed both
entries and found them valid; a GOES request stored its three hour
listings in the NOAA table.

## Invalidation and the prune job

Entries expire after:

- **90 days** for settled times, whose data ends more than 7 days ago:
  providers have finished ingesting them;
- **1 hour** for recent times, which may still get granules.

`YCGS_LOOKUP_SETTLED_DAYS`, `YCGS_LOOKUP_TTL_SETTLED_DAYS` and
`YCGS_LOOKUP_TTL_RECENT_HOURS` override these. DynamoDB deletes expired
items itself (within a day or two), and readers ignore expired items
before then.

A settled entry can still go stale: a granule reprocessed (new version),
replaced or withdrawn, as happens with provisional products like NISAR's.
The weekly job (`ycgs_titiler.prune.handler`, the tiler image with another
command, run by EventBridge Scheduler on Mondays at 07:00 UTC) recomputes
every settled entry and deletes it if the result changed; the next request
stores the new one. It also deletes expired entries and entries of a kind
this version doesn't know, and leaves short-lived entries to expire. A
recompute that fails keeps the entry. It stops recomputing a minute before
Lambda's 15-minute limit; the rest wait a week.

::: warning Design decision: a scheduled Lambda, not AWS Batch
AWS Batch needs a compute environment, a job queue and a job definition,
and a VPC with a route to the internet (CMR, NOAA). The job is a few
minutes of HTTP calls a week, well within one Lambda invocation, and the
tiler image already has the code; EventBridge Scheduler invokes it for
free.
:::

## Code

::: code-group
<<< @/../tiler/src/ycgs_titiler/lookups.py#lookup [lookups.py#lookup]
<<< @/../tiler/src/ycgs_titiler/granules.py#cached-backend [granules.py#cached-backend]
<<< @/../tiler/src/ycgs_titiler/granules.py#select [granules.py#select]
:::

`lookups.cached(kind, query, ttl)` returns the stored result of a lookup,
or computes and stores it. Each kind registers its function, so the prune
job can recompute any entry from its stored query:

| Kind | Query | Result |
|---|---|---|
| `cmr-granules` | titiler-cmr search parameters, parent tile, coverage tolerance | the parent's granules (titiler-cmr `Granule` JSON) and whether the list is complete |
| `cmr-times` | the `/datasets/{id}/times` CMR query, settled windows only | the window's granules (time, end, granule UR) |
| `goes-hour` | bucket and hour prefix, complete hours only | the hour's keys |

The infrastructure is in the regional module (`lookup_cache = true` for
the NASA and NOAA deployments):

::: code-group
<<< @/../terraform/tiler/modules/regional-api/main.tf#lookup-cache [modules/regional-api/main.tf#lookup-cache]
:::
