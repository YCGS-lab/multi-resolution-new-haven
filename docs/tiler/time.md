# Time resolution (`timeres.py`)

A request's `datetime` (and `datetime2` for difference renders) has to
become parameters that select data. The cheapest way depends on how the data
are laid out, so each dataset declares one of five **time kinds** in
`datasets.yaml`.

| Kind | Data layout | `datetime` becomes | Datasets |
|---|---|---|---|
| `granule` | Many files, found through CMR | CMR `temporal` filter (titiler-cmr searches and mosaics) | NISAR, SMAP, HLS, Black Marble |
| `dimension` | One store with a time dimension | `sel=time=nearest::T`, a lazy selection | ERA5-Land |
| `scan` | One file per satellite scan, named by its start time | The S3 URL of the nearest scan | GOES-19 ABI, GOES-19 LST |
| `template` | One file per step at a predictable URL | That URL | CHIRPS |
| `static` | No time | nothing | ASTER GDEM |

::: warning Design decision: one resolver per data layout
One mechanism for everything would be simpler to explain but expensive:
CMR knows nothing of NOAA or ECMWF data, and treating GOES as one dataset
would need an index of millions of files. Each kind uses the operation
that is already cheap for its layout: one CMR query, an index lookup on an
in-memory coordinate, one cached S3 listing per hour, or string formatting.
Adding a layout means adding a kind here and in `presets.py`, which forces
the cost question to be answered.
:::

## Parsing times <Badge type="tip" text="standard" />

ISO 8601. A year (`2025`) or month (`2026-07`) means its first day, a bare
date means midnight UTC, and times without a zone are UTC. Invalid input
raises `TimeError`, which becomes HTTP 400.

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#parse-datetime [timeres.py#parse-datetime]
:::

## Granules (CMR)

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#granule-time [timeres.py#granule-time]
:::

- **`align: day`, `month`, `year`** turn any time into the whole UTC day,
  month or year containing it. titiler-cmr mosaics that period's granules
  (NISAR sorts by `-start_date`, so the newest is on top).
- **`align: instant`** asks for granules whose time range contains that
  instant: for SMAP's 3-hourly files, exactly one.
- **An interval `start/end`** (what the website sends for SMAP and Black
  Marble: the selected timestep's window) is used as given.

::: danger Workaround: windows start one second in
CMR's `temporal` ranges are inclusive, and a granule's range usually ends
exactly where the next one starts: the 2024 Black Marble composite ends at
2025-01-01T00:00:00, SMAP's 18–21 h granule at 21:00:00. A 2025 search from
midnight would also return 2024's granule, and titiler-cmr would mosaic
both. So every window starts one second after its nominal start (and an
aligned window also ends one second before its end). The pipeline has the
same problem in its [Black Marble download](/pipeline/datasets/water-and-lights#viirs-black-marble).
:::

Listing available times (`/datasets/{id}/times`) queries the CMR granule
search directly over the catalog's New Haven `aoi`: one HTTPS request, no
data read.

::: tip
A client that already knows the granule can pass `granule_ur` and omit
`datetime`; the default `temporal` is then left out
([`resolve`](./requests#resolving-a-request)).
:::

## A time dimension inside one store

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#dimension-time [timeres.py#dimension-time]
:::

The output is titiler.xarray's `sel` syntax, `{dim}={method}::{value}`, with
`nearest` as the default method. Two times (for `diff`) become two `sel`
values on the same dimension, which the reader turns into a two-band array
([time steps as bands](./readers#stacking-into-bands)). The value has no `Z`
because NumPy's `datetime64` parser rejects time zones. Listing times opens
the store (cached) and slices its `time` coordinate.

## GOES scans

GOES-19 writes one NetCDF file per product, mode and scan under
`{product}/{YYYY}/{day-of-year}/{HH}/`. The file name carries the scan start
(`s20261541801179` = 2026, day 154, 18:01:17.9).

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#scan-time [timeres.py#scan-time]
:::

- **Nearest scan:** the resolver lists the hour before, the hour of and
  the hour after T (unsigned S3 `ListObjectsV2` calls; the bucket is
  public), parses the start times, and picks the closest. A `channel` in
  the time spec keeps only that band's files (`red-500m`).
- **Latest scan:** with no `datetime`, it walks back hour by hour (up to 4
  hours) and takes the newest scan. Such responses are not *pinned* and are
  cached for 60 s only ([caching](./requests#caching)).
- **Caching:** listings of hours that ended more than 15 minutes ago never
  change, so they are cached for the life of the container; more recent
  hours for 30 s.

::: warning Design decision: list S3 instead of keeping an index
The scan time could be computed from the scan schedule, but scans shift by
seconds and occasionally go missing. Listing is exact and cheap: an hour
holds 12 files in `ABI-L2-MCMIPC` (192 in `ABI-L2-CMIPC`, one per band and
scan, and one in the hourly `ABI-L2-LSTC`), which fit in one list response.
:::

`list_scans` (for `/times`) caps the window at 48 hours, because each hour
is one listing call.

## URL templates

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#template-time [timeres.py#template-time]
:::

The time (or an interval's start) is rounded down to its `step`, and the
URL's `{t:...}` fields are filled with `str.format` (strftime codes), e.g.
`chirps-v3.0.sat.{t:%Y.%m.%d}.tif`. Nothing is listed: the times available
are every step up to `latency_days` before now. The URL is not checked
first: a day the server does not have yet fails in the COG backend when it
opens the file, not with a 400 from the preset layer.

## Choosing the lister for `/times`

::: code-group
<<< @/../tiler/src/ycgs_titiler/timeres.py#list-times [timeres.py#list-times]
:::

The default windows (30 days of granules, 2 days of a dimension, 3 hours of
scans, 60 days of template steps) keep a bare `/times` request small. A
static dataset has no times.

## Tests

`test_presets.py` resolves every render of the real `datasets.yaml`, with
the GOES listing replaced by a recorded set of keys. The newer time kinds:

::: code-group
<<< @/../tiler/tests/test_presets.py#new-time-kinds [test_presets.py#new-time-kinds]
:::
