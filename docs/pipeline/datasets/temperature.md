# Temperature

Two satellite land surface temperatures (VIIRS at 750 m, GOES at 2 km),
matched to within 9 minutes of each other, and two air-temperature products
(ERA5-Land at 0.1°, PRISM at 800 m). Landsat's 100 m surface temperature is
covered with [Landsat](./optical#landsat-8).

VIIRS and GOES share one color scale (`styles.LST_RANGE`, 20–45 °C,
`inferno`), so their figures compare directly.

## VIIRS LST

**VNP21 v002 (Suomi NPP), 750 m swath, 2026-06-03 17:48–17:54 UTC.**
Scripts: `download.py`, `visualize.py`, `create-cog.py`.

::: warning Design decision: one screened granule
`download.py`'s docstring records the screening. 417 VIIRS LST granules were
narrowed by view angle to 35 near-nadir ones, by cloudiness in true-color
imagery to 6 clear ones, then by LST quality. This one was closest to nadir
(view angle 2.5–4°, so the pixels are near their nominal 750 m) and had a
cloud-free GOES-19 scan 9 minutes later. The screening code is not in the
repository; only its description is. The archive cannot subset swath files,
so the whole granule (~83 MB) is downloaded, pinned by name and a narrow
time window.
:::

### Swath to grid <Badge type="warning" text="decision" />

A [swath](/guide/glossary#swath) has a latitude and longitude per pixel and
no affine transform, so rasterio cannot reproject it. The scripts use
pyresample's k-d tree nearest-neighbor resampling instead:

::: code-group
<<< @/../scripts/viirs-lst/visualize.py#pixel-spacing [scripts/viirs-lst/visualize.py#pixel-spacing]
<<< @/../scripts/viirs-lst/visualize.py#kd-tree-resample [scripts/viirs-lst/visualize.py#kd-tree-resample]
:::

Each output pixel takes the nearest swath pixel center within
`0.6 × pixel diagonal`, just over half the diagonal, so there are no gaps.
The result is Voronoi cells: each swath pixel covers the area closer to it
than to any other, which is its footprint. Masked pixels (cloud, not
produced) stay in the tree as NaN. They keep their footprints, and their
neighbors do not grow into them.

The quality flags are kept as four classes (best, nominal, cloud, not
produced). The labeled figure hatches "nominal" pixels and grays out cloud.
The overpass time of the pixels over New Haven is estimated from the
granule's time span and the swath row (VIIRS scans 16 rows at a time).

::: code-group
<<< @/../scripts/viirs-lst/create-cog.py#swath-to-web-grid [scripts/viirs-lst/create-cog.py#swath-to-web-grid]
:::

The website COG uses the same k-d tree resampling onto a
[fine grid](../views-and-grids#fine-grids-for-the-website) sized from the
measured swath spacing. Its quality overlays are not carried over: cloud
and water are simply transparent.

## GOES LST

**GOES-19 ABI LSTC (CONUS, 2 km), scan 2026-06-03 18:01–18:04 UTC.**
Scripts: `download.py`, `visualize.py`, `create-cog.py`.

::: warning Design decision: product and hour
The CONUS product (LSTC) has the finest grid (2 km), a short well-defined
scan, and small files. The 18:01 scan is the hourly scan closest to the VIIRS
overpass, and all land pixels have the best quality flag; 17:01 had cloud
along the coast. `download.py` fetches that one object by its key from
NOAA's public S3 bucket over plain HTTPS: no search, no credentials.
:::

### Fixed-grid georeferencing <Badge type="warning" text="decision" />

ABI data are on a geostationary "fixed grid" of scan angles. The scripts
build the projection and the affine transform from the file's own
attributes, and check them:

::: code-group
<<< @/../scripts/goes-lst/visualize.py#abi-fixed-grid [scripts/goes-lst/visualize.py#abi-fixed-grid]
<<< @/../scripts/goes-lst/visualize.py#footprint-and-view-zenith [scripts/goes-lst/visualize.py#footprint-and-view-zenith]
:::

Scan angles times the satellite height give projection meters. The transform
is built from pixel centers minus half a pixel, and asserted to match the
file's `x_image_bounds`/`y_image_bounds` to within 5% of a pixel. That
catches a half-pixel error, the most common way to misplace geostationary
data. At New Haven's high viewing angle (about 48°), a pixel's ground
footprint is about 2.1 km east-west by 3.1 km north-south; the code
computes it from the geometry rather than assuming 2 km.

::: code-group
<<< @/../scripts/goes-lst/create-cog.py#geos-to-web-grid [scripts/goes-lst/create-cog.py#geos-to-web-grid]
:::

The website COG keeps only pixels with the top two quality flags (DQF 0 or 1).
Its fine grid is sized from the computed east-west footprint.

## ERA5-Land

**Hourly 2 m air temperature, 0.1°, 2026-07-20 at sunrise, solar noon,
sunset and the middle of the night.** Scripts: `select_day.py`, `timing.py`,
`download.py`, `visualize.py`, `create-cog.py`.

::: code-group
<<< @/../scripts/era5-land/select_day.py#clear-day-ranking [scripts/era5-land/select_day.py#clear-day-ranking]
:::

::: warning Design decision: a clear day and its preceding night
`select_day.py` ranks summer 2026 days by ERA5 total cloud cover over New
Haven: the daytime mean plus half the preceding night's mean. Both daytime
heating and night-time cooling then happen under clear skies, which
maximizes the day–night contrast the four maps show. Cloud cover comes from
ERA5 single levels (0.25°), because ERA5-Land has no cloud variable.
:::

::: code-group
<<< @/../scripts/era5-land/timing.py#sun-event-times [scripts/era5-land/timing.py#sun-event-times]
:::

The four times are computed with `astral` for New Haven Green and rounded to
whole hours, since ERA5 is hourly. "Night" is the midpoint between the
previous sunset and the day's sunrise, so all four times fall on the same
local day.

::: code-group
<<< @/../scripts/era5-land/download.py#days-x-hours-subset [scripts/era5-land/download.py#days-x-hours-subset]
:::

The Copernicus API returns every combination of the requested days and
hours. The four times can span two UTC dates, so the result is cut down to
exactly the four wanted times. All four maps, in both views, share one color
range, so the daily cycle can be read off them. The website COG has the
four times as four bands, one product each.

## PRISM

**Monthly mean air temperature, 800 m, July 2026 (provisional).** Scripts:
`download.py`, `visualize.py`, `create-cog.py`.

::: code-group
<<< @/../scripts/prism/download.py#clip-window [scripts/prism/download.py#clip-window]
:::

::: danger Workaround: two downloads per day
The PRISM service allows each file to be downloaded only twice a day per IP
address, and serves only the whole-country zip (~50 MB). `download.py` skips
the download if the clipped file exists. `--zip PATH` reuses a zip already
downloaded. Errors can come back with HTTP 200, so the response type is
checked. The clip is written untiled, because the source COG's tiling does
not fit the small window.
:::

The color range, 22.75–24.0 °C, is set by hand around the observed 22.9–23.8 °C. PRISM models
air temperature over water too, so Long Island Sound has values, unlike the
land-only datasets.
