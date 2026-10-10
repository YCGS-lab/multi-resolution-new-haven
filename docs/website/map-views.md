# Map views

`website/js/mapview.js` holds what the Viewer and the Grid share: view-state
handling, landmark layers, the loading message, and the HTML around a map
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

- The map cannot zoom out past the whole extent (`fitZoom`). It cannot zoom
  in past 64 screen pixels per meter (`MAX_ZOOM = 6`), about 5 px per 7.6 cm
  pixel of the finest data.
- It cannot pan past the extent's edges. When the extent is narrower than
  the map on one axis, it is centered on that axis.

The project is about one place, so there is nothing to see outside the
extent.

## Loading state <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#loading-state [website/js/mapview.js#loading-state]
:::

Every tile request calls `start()` and `end(error)`. After 250 ms with
requests pending, "Loading…" appears; failures are counted and reported. The
delay avoids a flicker on fast loads. COG, ArcGIS and XYZ layers all report
through it, and the benchmark uses it to detect when a map has settled.

## Landmarks <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#landmark-layers [website/js/mapview.js#landmark-layers]
:::

A `ScatterplotLayer` for the markers and a `TextLayer` for the names, with
an outline so they read on any background. They match the figures' style.
The marker color comes from each product (`landmark_color`), e.g. yellow on
gray hillshades.

## Axes, scale bar and keys <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/mapview.js#map-chrome [website/js/mapview.js#map-chrome]
:::

Axes and the scale bar are HTML, positioned from the world view state.
Ticks are longitudes and latitudes at a round step (0.01°, 0.02°, 0.05°, ...)
chosen to fit the width. The scale bar is a round length (1, 2 or 5 × 10ⁿ)
up to a fifth of the map width. Its ground length uses the Mercator scale
at the map center. `update` returns early when nothing changed, because it
runs on every frame.

::: code-group
<<< @/../website/js/mapview.js#key-html [website/js/mapview.js#key-html]
:::

The colorbar is a CSS gradient of the render spec's 256 colors. It has
under/over boxes for `extend`, and ticks on a linear or log scale; the
legend comes from the product's entries. Text from the catalog is escaped
before it goes into `innerHTML`.
