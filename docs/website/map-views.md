# Map views

`website/js/mapview.js` holds what the Viewer and the Grid share: view-state
handling, the selected place's marker, the loading message, and the HTML around a map
(axes, scale bar, title, colorbar or legend).

## World view state and deck.gl's MapView <Badge type="warning" text="decision" />

The app's view state is `{target: [x, y], zoom}` in
[world coordinates](./catalog#three-coordinate-systems): `2^zoom` screen pixels
per Web Mercator meter. deck.gl's `MapView` takes `{longitude, latitude,
zoom}`, where zoom 0 shows the whole world in 512 pixels. Both are Web
Mercator, so converting is a shift of the center and a constant offset of
the zoom:

```
pixels per meter = 2^zoom_world = 512 · 2^zoom_map / C   (C = 2π · 6378137 m)
⇒ zoom_map = zoom_world + log2(C / 512) ≈ zoom_world + 16.26
```

::: code-group
<<< @/../website/js/mapview.js#deck-view-state [website/js/mapview.js#deck-view-state]
:::

The Viewer and Grid keep the world view state. They convert it in two
places:
- in `setProps({viewState: toDeckViewState(...)})` when drawing;
- in `onViewStateChange` when the user pans or zooms. deck.gl's proposal is
  converted back with `fromDeckViewState`, clamped, and returned converted
  again, so deck.gl uses the clamped state.

`CONTROLLER` turns off rotation and tilting, which the old orthographic view
did not have and these flat maps do not need.

::: warning Trade-off
The extra conversion is a few lines. In exchange, zoom limits, axes, the
scale bar, swipe and spy positions and the URL format work unchanged. The
alternative was to rewrite them all in longitude/latitude. The deepest zoom
(world zoom 6, ≈ MapView zoom 22.3) is beyond deck.gl's default `maxZoom`
of 20, so the converted state passes `minZoom`/`maxZoom` explicitly.
:::

## Pan and zoom limits <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/mapview.js#clamp-view-state [website/js/mapview.js#clamp-view-state]
:::

- The maps open on (and **⤢** / `0` return to) the Greater New Haven
  extent, but pan anywhere: the limits are the Web Mercator world
  (`catalog.limits`), and the map cannot zoom out past slippy-map zoom 3
  (about the contiguous US on a screen). It cannot zoom in past 64 screen
  pixels per meter (`MAX_ZOOM = 6`), about 5 px per 7.6 cm pixel of the
  finest data.
- It cannot pan past the limits' edges. When they are narrower than the map
  on one axis, the map is centered on that axis.

Most live datasets cover the contiguous US or the world. Each product says
where it has data (`coverage`: Connecticut for the CT ECO services, the
contiguous US for NAIP and 3DEP, the stored area for pre-built COGs) and
from which zoom it may be drawn (`min_zoom`, a slippy-map zoom: 12 for the
CT orthoimagery and lidar, 11 for NAIP, 10 for 3DEP, 9 for Planet and NISAR,
7 for Landsat, 5 for ERA5-Land, ...), so huge high-resolution mosaics are
never requested for large areas. Outside its coverage or below its zoom, a
map draws nothing for the product and says why ("Dataset unavailable here",
"Zoom in to view this dataset"); when the selected timestep has no data in
view, "Timestep not available here". See
[Time, live data and credentials](./time#why-an-image-is-not-drawn).

## Loading state <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#loading-state [website/js/mapview.js#loading-state]
:::

Every tile request calls `start()` and `end(error)`. After 250 ms with
requests pending, "Loading…" appears; failures are counted and reported. The
delay avoids a flicker on fast loads. COG, ArcGIS and XYZ layers all report
through it, and the benchmark uses it to detect when a map has settled.

## The selected place <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#place-marker [website/js/mapview.js#place-marker]
:::

A searched place ([Place search](./search)) gets a white dot with a
Yale-blue ring on every map; a starred place (an area) gets none. `placeExtent`
turns the place into the extent the maps fit when it is selected and when ⤢ or
`0` is pressed: its box, at least ~800 m across (an address comes as a point
or a tiny box), or the catalog's extent when no place is selected.

The landmark labels of earlier versions (New Haven's, with a Labels toggle)
are gone: the street maps name places better, everywhere. The figures still
draw them (`data/landmarks.json`, `render.py`).

## Axes, scale bar and keys <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#map-chrome [website/js/mapview.js#map-chrome]
:::

Axes and the scale bar are HTML, positioned from the world view state.
Ticks are longitudes and latitudes at a round step (0.00001°, 0.00002°,
0.00005°, ... about 1 m at the finest) chosen to fit the width. The latitude
axis is as wide as its longest label at the deepest zoom ("85.00000°N"),
measured at start-up with the page's font (`fitLatitudeAxis`), so no
browser's font rendering cuts the labels off. The scale bar is a round length (1, 2 or 5 × 10ⁿ)
up to a fifth of the map width. Its ground length uses the Mercator scale
at the map center. `update` returns early when nothing changed, because it
runs on every frame.

::: code-group
<<< @/../website/js/mapview.js#key-html [website/js/mapview.js#key-html]
:::

The colorbar is a CSS gradient of the render spec's 256 colors. It has
under/over boxes for `extend`, and ticks on a linear or log scale; the
legend comes from the product's entries. The source block at the bottom
gives the product's description (`subtitle`: bands, units) and its
credits. Under the title, `titleHTML` puts the selected time and the
product's "More info" and "Data access" links (`links` in the catalog, from
`LINKS` in `scripts/website/build_catalog.py`; they open in a new tab) on
one line, the links in a fixed-width column after the time so they stay
put as the time changes; only a long label (a time window) pushes them
right. Grid slots keep the compact one-line time and subtitle, without
links. Text from the catalog is escaped before it goes into `innerHTML`.
