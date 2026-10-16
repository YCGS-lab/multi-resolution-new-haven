# Time, live data and credentials

Most images change over time. The website lets the user pick a timestep for
every image, reads the data for it straight from the original APIs (no
pre-fetching for those datasets), and says clearly when an image cannot be
shown here and why. This page covers the pieces, from the catalog to the
pixels, and the two tabs built on them: Animation and ICESat-2.

```mermaid
flowchart LR
  Spec["product.time<br/>(web.py time_spec)"] --> Slot["Slot (slot.js)<br/>selection + view"]
  Slot -->|"area in view"| Avail["availability()<br/>(time.js)"]
  Avail -->|"STAC / CMR / Planet /<br/>list / hourly"| Steps["Steps"]
  Steps --> Slot
  Slot --> TC["TimeControl<br/>(timecontrol.js)"]
  TC -->|"setTime()"| Slot
  Slot -->|"ctx()"| Tiles["productLayers()<br/>(tiles.js)"]
  Tiles --> PC["Planetary Computer<br/>mosaics"]
  Tiles --> CMR["titiler-cmr"]
  Tiles --> AG["ArcGIS services<br/>per year"]
  Tiles --> XYZ["XYZ templates<br/>(Planet)"]
  Tiles --> CDS["CDS jobs + GRIB<br/>(cds.js, grib.js)"]
```

## The time spec

Each dataset's `website-layers.py` (or `create-cog.py`) gives its products a
time spec through `write_spec(..., meta)`; `build_catalog.py` copies the
dataset's `meta` into each product (a product's own keys win), so in the
browser every product has `time`, `requires`, `coverage` and `min_zoom`.

::: code-group
<<< @/../scripts/common/web.py#time-spec [scripts/common/web.py#time-spec]
<<< @/../scripts/common/web.py#requirements [scripts/common/web.py#requirements]
:::

| Dataset | Step | Timesteps from | Widget | Window | Filters | Requires |
|---|---|---|---|---|---|---|
| Landsat 8-9 | day | Planetary Computer STAC | calendar | yes (latest / median / average) | max cloud cover | — |
| NAIP | year | Planetary Computer STAC | drop-down | — | — | — |
| CT orthoimagery | year | fixed list (1934-2023) | drop-down | — | — | — |
| CT lidar | year | fixed list (2016, 2023) | drop-down | — | — | — |
| Planet basemaps | month | Planet Basemaps API | month grid | — | — | Planet key |
| ERA5-Land | hour | every hour, 1950 to −6 days | calendar + hour | — | — | CDS key |
| NISAR GCOV | day | CMR | calendar | yes | — | — |
| SMAP L4 (live) | time (3-hourly) | CMR | calendar + time | — | — | cloud |
| Black Marble (live) | year | CMR | drop-down | — | — | cloud |
| Pre-built COGs | one timestep | fixed list of one | label | — | — | — |

Keys are strings that sort in time order: `"2023"`, `"2026-07"`,
`"2026-07-20"`, `"2026-07-20T14:00Z"`.

<<< @/../website/js/time.js#time-keys

## Which timesteps have data in view

`availability(catalog, product, bbox)` lists the timesteps over the area in
view (rounded out a little, so small pans reuse the last answer; cached;
for views larger than 2°, only their central 2° box, so searches stay fast
when zoomed out over a region).
`Steps` is a sorted set with the questions the UI asks (latest, previous /
next with data, days with data in a month, timesteps of a day);
`HourlySteps` answers the same for "every hour" without listing 650 000
hours.

::: code-group
<<< @/../website/js/time.js#availability [availability()]
<<< @/../website/js/time.js#avail-stac [STAC]
<<< @/../website/js/time.js#avail-cmr [CMR]
<<< @/../website/js/time.js#avail-planet [Planet]
<<< @/../website/js/time.js#avail-list [fixed list]
<<< @/../website/js/time.js#steps [Steps]
:::

STAC items keep their properties (e.g. `eo:cloud_cover`), so the filters
(`applyFilters`) apply in the browser without asking again. Filters default
to keeping every image (max cloud cover 100%).

## One map's selection: Slot

A `Slot` holds one map's product and time selection, the timesteps over its
view, and whether the image can be drawn here at all. Viewer A and B, every
grid slot and the animation each have one.

::: code-group
<<< @/../website/js/slot.js#selection [selection and URL]
<<< @/../website/js/slot.js#slot [Slot]
:::

- **Default: the latest.** A new selection is `auto`: it follows the latest
  timestep with data in view (re-resolved when the view moves), until the
  user picks one. "Latest" returns to auto.
- **Same dataset, same time.** Switching between products of one dataset
  (Landsat true color → urban false color) keeps the date.
- **URL.** `a=landsat/truecolor@2026-06-01..2026-08-31;px=median;cc=30`:
  product, timestep, optional end, and options / filters that differ from
  the defaults.

### Why an image is not drawn

<<< @/../website/js/slot.js#slot-blocker

`status()` adds the time questions: still listing timesteps, no imagery in
view, no imagery on the selected date here ("Timestep not available"). The
maps draw nothing for the slot and show the reason in the middle of the map,
with an "Enter API key" button for locked datasets:

<<< @/../website/js/mapview.js#map-notice

## The time control

<<< @/../website/js/timecontrol.js#tc-build

- **Drop-down** for a few isolated timesteps (survey years, ≤ 40 timesteps
  in view), newest first, with the dataset's labels ("1934: Fairchild Aerial
  Surveys, black and white").
- **Calendar** for many: days with imagery in view are highlighted, the rest
  grayed out; ⏮ / ⏭ jump to the previous / next month with data; months for
  monthly datasets; a time-of-day drop-down when a day has several
  timesteps (hourly, 3-hourly).
- **◀ ▶** step to the previous / next timestep with data in view (also `,` /
  `.` for image A).
- **Advanced** (datasets with a window): an end date (any day up to the
  dataset's limit) and how the images in between are combined: latest,
  median or average pixel. The images are mosaicked by the tiler.
- **Filters** inline, e.g. max cloud cover.
- Hidden while the image cannot be shown at all (locked, cloud only,
  outside its coverage).

<<< @/../website/js/timecontrol.js#calendar

## Live sources

The time context (`slot.ctx()`: timestep, window as ISO times, options,
filters, the timestep's parameters) goes to `productLayers`, which picks
the source by type. All tiled live sources share one renderer interface and
one tile cache, which the animation fills ahead of time.

<<< @/../website/js/tiles.js#tile-cache

### Planetary Computer mosaics

::: code-group
<<< @/../scripts/common/web.py#pc-mosaic-source [web.py]
<<< @/../website/js/tiles.js#pc-register [register]
<<< @/../website/js/tiles.js#pc-tile [tiles]
<<< @/../website/js/tiles.js#parse-npy [NPY]
:::

For each selection a mosaic search is registered once (CQL2: the
collection, the date or window, the filters, the source's own conditions
such as Landsat 8-9 only; newest first, so "first" is the latest pixel).
Tiles are 512 px (`@2x`) NPY arrays of the bands the render spec reads plus
a mask band; the browser applies the scale factors and colors them with the
same CPU code as the ArcGIS tiles. 8-bit imagery (NAIP) comes as PNG.

::: warning Design decision: raw values, colored in the browser
Rendered PNGs from the tiler would be smaller (a 512 px, 3-band Landsat
NPY tile is 2 MB uncompressed), but the render specs (stretches, gamma,
colormaps with under / over colors, expressions) and colorbars would have
to be re-expressed as tiler parameters. Raw tiles keep one rendering path
for every source.
:::

### titiler-cmr (NASA Earthdata)

::: code-group
<<< @/../scripts/common/web.py#titiler-cmr-source [web.py]
<<< @/../website/js/tiles.js#titiler-cmr-tile [tiles]
:::

The service URL comes from `env.json`: `titiler_cmr` is the public NASA
VEDA deployment (NISAR works through it from anywhere, slowly);
`earthdata_tiler` is for a deployment with Earthdata S3 credentials for the
DAACs the public one cannot read (SMAP, Black Marble), which only the cloud
deployment would have.

### ArcGIS services per year, XYZ templates

An ArcGIS source's `variants` replace its URL, resolution and band ids for
a timestep (one CT ECO service per flight year). An XYZ URL may contain
`{time:mosaic}` (the timestep's parameter, e.g. Planet's mosaic name) and
`{credential:planet}` (the user's key; never in the catalog).

### ERA5-Land from the Climate Data Store

::: code-group
<<< @/../scripts/common/web.py#cds-source [web.py]
<<< @/../website/js/cds.js#cds-area [area]
<<< @/../website/js/cds.js#cds-fetch [jobs]
<<< @/../website/js/tiles.js#cds-layer [layer]
:::

The CDS is a job queue, not a tile service: a request (variable, days,
hours, area, GRIB) is submitted with the user's key, polled until it
succeeds, and its result file downloaded. The area is the view grown to at
least 4° and snapped to whole degrees (at most 12°), so small pans reuse
it. The map shows the queue status while waiting. The GRIB file is decoded
in the browser:

::: code-group
<<< @/../website/js/grib.js#grib-decode [decodeGrib]
<<< @/../website/js/grib.js#grib1 [GRIB 1]
<<< @/../website/js/grib.js#grib2 [GRIB 2]
:::

Both editions were checked against ecCodes on ECMWF sample files (values,
grid, bitmap, scanning direction); the whole flow was tested with mocked CDS
responses, not against the real service (no key).

## Where the website runs, and credentials

::: code-group
<<< @/../website/js/env.js#load-env [env.json]
<<< @/../website/js/env.js#requirement [requirement()]
<<< @/../website/js/env.js#credentials-store [credentials]
<<< @/../website/js/env.js#credentials-dialog [dialog]
:::

- **Cloud only.** `env.json` `"cloud": "auto"` means: the deployed site (any
  host but localhost) is the cloud; local testing is not. Products with
  `requires.cloud` are grayed out with a ☁ icon locally (and wherever the
  named service is not configured), with the reason as a tooltip. `?cloud=1`
  in the page URL pretends to be in the cloud, for testing.
- **Credentials.** The 🔑 Credentials button opens a dialog for the Planet
  and CDS keys. Keys stay in the browser: sessionStorage, or localStorage
  with "Remember", and are only sent to their provider. Products needing a
  missing key are grayed out with a 🔒 icon; picking one opens the dialog.

## Comparing through time

<<< @/../website/js/viewer.js#compare-through-time

Turning Compare on makes B the same image as A one timestep earlier (like
NASA Worldview's comparison), shown with the swipe divider, opacity or the
spy lens; each of A and B has its own time control, and "A, earlier" resets
B that way. The grid's slots each have a time control too, so one image at
several dates can sit side by side.

## Animation tab

::: code-group
<<< @/../website/js/animation.js#anim-frames [frames]
<<< @/../website/js/animation.js#anim-load [Load imagery]
<<< @/../website/js/animation.js#anim-play [play]
:::

Pick an image and a start and end date (by default the latest ~20
timesteps in view; for hourly data the last day, every N hours); the frames
are the timesteps with data in view between them, after the filters (at
most 120). **Load imagery** fetches and renders every frame's tiles for the
area in view into the tile cache (six requests at a time, with a progress
bar), as Worldview does; ERA5 hours are requested in one CDS job per month.
The slider jumps between frames; Play steps through them at 0.5-8 frames
per second, looping or not (space: play / pause, ← →: step). The last fully
loaded frame stays underneath the current one until it has loaded, so
frames never flash to gray. Panning after loading still works (new tiles
load live); the button then offers to reload for the new view.

## ICESat-2 tab

::: code-group
<<< @/../website/js/icesat2.js#is2-arrow [arrow]
<<< @/../website/js/icesat2.js#is2-profile-events [profile events]
<<< @/../website/js/icesat2.js#is2-profile-draw [profile drawing]
:::

The left map shows the sample beam passes (from `icesat2-profiles.json`,
written by `icesat2/create-cog.py` from the downloaded files; the canopy
height raster is unchanged and can be shown underneath). Clicking a beam
selects it. The right side draws its classified ATL03 photons (elevation
against distance along track, noise and unclassified first) on a canvas.
An arrow on the map (rotated along the track) and a dashed line in the
profile mark the same point: dragging the arrow snaps it to the nearest
point on the track, dragging (or clicking) in the profile moves the line;
each moves the other. The wheel zooms the profile, double-click shows the
whole line. Below the plot: the position, coordinates, and the ground and
canopy-top heights from the photons within ±15 m.
