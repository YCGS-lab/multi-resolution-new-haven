# Evaluation: a hybrid Icechunk store (virtual full resolution, stored overviews)

Question: instead of caching rendered tiles ([tile cache
evaluation](./tile-cache-evaluation)), cache the *data*: an Icechunk
repository per dataset whose full-resolution arrays are virtual references
to the original granules' chunks (HDF5, NetCDF, COG) and whose overviews
(coarser levels for low zooms) are computed once and stored as real chunks
in the repository. Same cache model: the first request for a granule
builds its entry, later requests read the store. How does it compare with
a tile cache?

Short answer: for the website's tiles the tile cache is better (the
hypothesis holds): ~10x faster per tile on a CloudFront miss, simpler, and
it only stores what people look at. Icechunk is the better tool for a
different job: fast arbitrary reads of the data (any render, point and
time-series queries, animation over many times, analysis), and it pays off
for a few datasets whose granules share a fixed grid (SMAP L4, GOES,
VIIRS / Black Marble tiles) or are slow to open (NISAR). The two can be
stacked: Icechunk underneath for the data, a tile cache on top for the
website.

## What it would change in the tiler

The tiler already reads Zarr by URL (`/xarray`, `readers.open_dataset`)
and already switches group by zoom (`zooms` in `datasets.yaml`, used for
NISAR's frequency A / B), which maps directly onto overview levels. A
dataset would become: open the repository (Icechunk reads the branch ref,
the snapshot and the manifests: 3-5 S3 GETs, ~50-150 ms, once per
execution environment), pick the level for the zoom, `sel` the time, read
the chunks. No CMR search and no HDF5 metadata parsing per request: the
references already say which bytes to read.

## Per request

| | Today (on a CloudFront miss) | Icechunk hybrid | Tile cache |
|---|---|---|---|
| Find the data | CMR search (0.13-20 s; less with the [lookup cache](./lookup-cache)) or GOES listing | manifest lookup in memory | key lookup |
| Open | HDF5 / NetCDF metadata over HTTP range reads (NISAR: seconds) | none (references) | none |
| Low zoom | reads full-resolution chunks across the tile (slow for NISAR at zoom 6-9 and HLS at 8-10) | stored overview chunks, in-region | stored image |
| High zoom | original chunks | original chunks via references (same bytes, same source bucket) | stored image |
| Render | per request, 0.2-1 s CPU | per request, 0.2-1 s CPU | none |
| Typical | 0.5-25 s | ~0.3-2 s | ~0.05-0.15 s |

A tile cache hit skips the Lambda entirely; an Icechunk read still runs
the tiler, reads chunks and renders. The Icechunk store does help *every
first view* (any tile, any render, any time already ingested), which a
tile cache can't: its first view of each tile is a full render.

## Storage and build cost

| | Icechunk hybrid | Tile cache |
|---|---|---|
| What is stored | per granule: references (KB-MB of manifests) plus overview levels for the whole granule (about 1/3 of the full-resolution size before compression) | only tiles that were requested |
| Example: one NISAR GCOV frame-date | references ~1 MB; overviews of 2 float32 bands at 10 m over ~240 km: ~1.5 GB raw, ~0.5-0.8 GB compressed | one viewport ~20-40 tiles x 100 KB = 2-4 MB per render |
| Example: SMAP L4, one 3-hourly granule | references only (9 km global grid needs no overviews): ~100 KB | ~1 tile per view |
| Build | references: parse metadata (seconds per granule). Overviews: read the whole granule once (NISAR: GBs, minutes; more than a tile request can wait for), so a background job, not the request path | rendered during the first request |
| Request path on a miss | must read the original anyway; ingest asynchronously | render and store (+30-50 ms) |
| S3 storage price | $0.023/GB-month: ~$0.02 per NISAR frame-date per month | ~$0.0001 per viewport per month |

Overviews are paid per granule, whether or not anyone looks at most of it;
tiles are paid per view. For a site centered on one city that is a large
difference: a NISAR frame is ~240 km wide and the site shows ~30 km.

## Complexity and risks

- **One ingestion pipeline per data format.** VirtualiZarr parsers for
  HDF5 (NISAR, SMAP, VIIRS HDF-EOS5), NetCDF (GOES) and TIFF (HLS, ASTER,
  CHIRPS), plus the fixes the readers already make (the grids without
  coordinates in `GroupedXarrayGranuleReader`, GOES's fixed-grid scan
  angles), now applied at ingest instead of at read.
- **Stacking granules.** Virtual references work when granules share a
  grid: SMAP L4 (one global EASE grid, a time axis), GOES CONUS (one fixed
  grid, a scan every 5 minutes), VIIRS and Black Marble (fixed 10° tiles).
  HLS (MGRS tiles in several UTM zones) and NISAR (frames on varying UTM
  grids) can't be one array without resampling, which is no longer
  virtual: they become one store (or group) per granule, and something
  still has to find which granules cover a tile (the role CMR and the
  lookup cache play now).
- **Credentials.** References into NASA Earthdata buckets need the DAAC's
  temporary S3 credentials (1 hour) at read time; the readers already get
  them from titiler-cmr, but they would have to be passed to Icechunk's
  virtual chunk containers per DAAC.
- **Stale references.** A reprocessed or withdrawn granule (NISAR's are
  provisional) leaves references to objects that no longer exist, or that
  changed: Icechunk can record an ETag or last-modified per reference and
  fail on a mismatch, and a job like the lookup cache's prune would have
  to find and rebuild them.
- **Concurrent writers.** Lazily adding granules from many Lambdas means
  concurrent commits; Icechunk detects conflicts and can rebase
  non-overlapping changes, but a single ingest job per dataset is simpler.
- **New dependencies** in the Lambda image: `icechunk`, and
  `virtualizarr` for the ingest job.

## Where Icechunk is the better choice

| Need | Better |
|---|---|
| Website tiles, revisits | tile cache |
| Website tiles, first views of ingested data | Icechunk (no search, no metadata parsing, overviews) |
| Another render or a changed color scale | Icechunk (the tile cache stores each render) |
| Point values and time series (`/point`, charts) | Icechunk (one read across the time axis instead of a granule per time) |
| Animation over many times on a fixed grid (SMAP, GOES) | Icechunk |
| Analysis outside the website (notebooks reading the same store) | Icechunk |
| Cost per view, simplicity | tile cache |

## Recommendation

Build the tile cache for the website first (see its evaluation). Consider
Icechunk later, per dataset, where the data access itself is the problem:

1. **SMAP L4 and GOES**: a time-stacked virtual store (no overviews needed
   for SMAP; GOES CONUS perhaps one or two levels), appended by a
   scheduled job. Fast animation and point time series.
2. **NISAR GCOV**: per-frame stores with stored overviews, built by a job
   when a new frame over the area appears, because opening the HDF5 and
   reading full resolution at low zoom is what makes its tiles take 5-10 s.
3. Not HLS, ASTER, CHIRPS or ERA5-Land: COGs already have overviews, and
   ERA5-Land is already an analysis-ready Zarr.
