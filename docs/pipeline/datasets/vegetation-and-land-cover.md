# Vegetation and land cover

Two datasets that are not images: ICESat-2's laser measurements (points
along ground tracks) and Connecticut's impervious-surface polygons. Both
have to be rasterized before the website can show them, and both raise
the question of how to show sparse or very detailed data at every zoom.

## ICESat-2

**ATL08 canopy height in 20 m segments, growing seasons 2019–2026, and ATL03
photon profiles along three sample lines.** Data from SlideRule Earth's
public service (no credentials). Scripts: `download.py`, `visualize.py`,
`create-cog.py`.

### Download

::: code-group
<<< @/../scripts/icesat2/download.py#atl08x-segment-request [scripts/icesat2/download.py#atl08x-segment-request]
:::

SlideRule's `atl08x` endpoint returns the land/vegetation segments in a
polygon for each growing season (May–September). Each 100 m segment carries
five 20 m sub-segments as arrays. They are exploded into points, and the
float32 fill value (3.0e38) becomes NaN. The request parameters are saved
next to each file.

::: code-group
<<< @/../scripts/icesat2/download.py#sample-line-selection [scripts/icesat2/download.py#sample-line-selection]
:::

::: warning Design decision: how the profile lines are chosen
Two lines come from the best-covered 2025–2026 passes: distinct granules,
spanning at least 5 km in the view. No 2025–2026 pass crosses the central
view, so the third line can come from any season. It must cross the central
view; night passes are preferred (less solar noise), then leaf-on months.
Lines are numbered west to east. Their photons come from the `atl03x`
endpoint with all photons kept (`cnf=0`), including background noise, so the
profile can show every photon class.
:::

### Rasterizing footprints <Badge type="warning" text="decision" />

::: code-group
<<< @/../scripts/icesat2/create-cog.py#burn-footprint-discs [scripts/icesat2/create-cog.py#burn-footprint-discs]
:::

Each 20 m point becomes a disc the size of the laser footprint: 12 m across
for canopy points, slightly smaller for ground-only points. Discs are burned
into a 2.5 m grid, newest pass last, so repeat tracks show the latest data.
Ground meters are scaled to Mercator units (`merc_scale`). The sample lines
become 12 m-wide ribbons coded by line number.

::: code-group
<<< @/../scripts/icesat2/create-cog.py#dilated-products [scripts/icesat2/create-cog.py#dilated-products]
:::

::: warning Design decision: grow sparse points on screen
Zoomed out, a 12 m disc is far smaller than a screen pixel and would
disappear. The render spec sets `dilate_px` (2 or 3): the website grows data
pixels by that many screen pixels into transparent neighbors, so tracks stay
visible at any zoom and keep their true size when zoomed in. See
[COG layers](/website/cog-layers#dilate-px). The products are layered over a
desaturated, lightened OpenStreetMap basemap, read live.
:::

## CT impervious surface 2023

**Impervious-surface polygons (buildings, roads, driveways, ...), 11 classes,
from the CT GIS Office FeatureServer.** Scripts: `download.py`,
`visualize.py`, `create-cog.py`.

### Download <Badge type="warning" text="decision" />

::: code-group
<<< @/../scripts/ct-impervious-2023/download.py#tiled-paginated-query [scripts/ct-impervious-2023/download.py#tiled-paginated-query]
:::

::: danger Workaround: slow pagination
About 370 000 polygons fall in the views. One query over the whole area,
paged with `resultOffset`, takes 30–60 s per page on the server. The area is
split into 1.5 km tiles, each paged on its own (~2 s per page), with six
threads. Every page is cached on disk, with a marker per finished tile, so
an interrupted run resumes. Polygons crossing tile edges appear in several
tiles and are de-duplicated by `OBJECTID`.
:::

::: code-group
<<< @/../scripts/ct-impervious-2023/download.py#esri-ring-assembly [scripts/ct-impervious-2023/download.py#esri-ring-assembly]
:::

::: danger Workaround: assemble polygons from Esri JSON
The service's GeoJSON output turns the holes of large polygons (a town-wide
road network with thousands of city-block holes) into extra overlapping
parts. The script asks for Esri JSON instead and assembles polygons itself:
clockwise rings are shells and counter-clockwise rings are holes (Esri's
convention). Each hole goes to the smallest shell containing it.
:::

### Rasterizing <Badge type="warning" text="decision" />

Classes are burned in a fixed order (later classes over earlier ones:
bridges over roads, buildings over everything). The figures rasterize at
each view's pixel centers. The website COG is a 0.5 m uint8 raster of the
whole extent, about 43 000 × 24 000 pixels, rasterized in strips of 2048
rows to bound memory:

::: code-group
<<< @/../scripts/ct-impervious-2023/create-cog.py#strip-rasterization [scripts/ct-impervious-2023/create-cog.py#strip-rasterization]
:::

It is written as a lossless categorical COG (DEFLATE, mode overviews) with
no no-data value, since 0 ("not impervious") is a real, drawn class. The
"impervious / not" product recolors the same band with a second categorical
table.
