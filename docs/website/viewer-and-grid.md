# Viewer, compare and grid

Two tabs, two classes: `Viewer` (`viewer.js`), one large map with an
optional comparison, and `Grid` (`grid.js`), any number of maps with shared
pan and zoom.

## The Viewer <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/viewer.js#viewer-deck [website/js/viewer.js#viewer-deck]
:::

One `Deck` with one `MapView`. The Viewer keeps the
[world view state](./map-views#world-view-state-and-deck-gl-s-mapview) and
clamps every change deck.gl proposes. Every state change (pan, product,
comparison mode) calls `update()`, which schedules at most one redraw per
animation frame:

::: code-group
<<< @/../website/js/viewer.js#render-throttle [website/js/viewer.js#render-throttle]
:::

## Comparing two images

With Compare on, image B is drawn over image A in one of three ways:

| Mode | B shows | Implemented with |
|---|---|---|
| **Swipe** | right of a draggable divider | deck.gl `ClipExtension` |
| **Opacity** | everywhere, faded | layer `opacity` |
| **Spy** | inside a circular lens that follows the cursor | deck.gl `MaskExtension` and a circle polygon as mask |

::: code-group
<<< @/../website/js/viewer.js#compare-layers [website/js/viewer.js#compare-layers]
:::

Layer order: gray no-data background, A, then (for swipe and spy) a second
background clipped like B, then B, then the lens ring and the landmarks.
B's own background keeps A from showing through B's no-data pixels inside
the swipe or the lens.

### Comparison props per coordinate system <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/mapview.js#overlay-props [website/js/mapview.js#overlay-props]
:::

::: warning Why the clip bounds depend on the layer
`ClipExtension` compares each fragment's position with `clipBounds`, both
in the layer's own coordinates. Most layers use longitude/latitude, so the
swipe line is converted to a longitude. deck.gl-raster draws COG tiles as
meshes in deck.gl's Web Mercator *common space* (512 units around the
world), so for COG layers the line is converted to common-space x. Also,
the extension's default for single-mesh layers is to clip whole instances
by their anchor point, which would show or hide a whole tile at once.
`clipByInstance: false` makes it clip per pixel. `MaskExtension` draws the
lens into a mask texture that covers the viewport and tests each pixel against
it, so it needs neither adjustment.
:::

The divider is a DOM element over the map. It can be dragged with the
pointer or moved with the arrow keys:

::: code-group
<<< @/../website/js/viewer.js#swipe-handle [website/js/viewer.js#swipe-handle]
:::

## The Grid

Each slot has its own image picker, title, axes and key (HTML), and
shares one view state with the other slots. Rows can be added. A Rearrange
mode lets the user drag images between slots (HTML drag and drop):

::: code-group
<<< @/../website/js/grid.js#grid-drag [website/js/grid.js#grid-drag]
:::

### One canvas for the grid <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/grid.js#grid-deck [website/js/grid.js#grid-deck]
<<< @/../website/js/grid.js#grid-render [website/js/grid.js#grid-render]
:::

::: warning Design decision: one WebGL canvas, one view per slot
Browsers cap the number of live WebGL contexts (often 16) and drop the
oldest beyond that. A `Deck` per slot would break past a dozen slots and
re-create shaders and textures for each. The Grid has **one** `Deck` on one
canvas, fixed behind the page (`#grid-deck`). Each visible slot gets a
`MapView` placed over its map area, and `layerFilter` sends each slot's
layers only to its own view. The slots' HTML lies on top. Their map areas
are transparent "holes" that let pointer events through to the canvas
(CSS below). Slots scrolled out of sight get no view, so nothing is drawn
or loaded for them.
:::

::: code-group
<<< @/../website/js/grid.js#grid-layout [website/js/grid.js#grid-layout]
:::

On scroll, resize or layout changes, the views are re-placed over the slots.
When slots change size (e.g. a different number of columns), the zoom
changes so the same ground extent stays visible.

::: code-group
<<< @/../website/css/style.css#grid-canvas-css [website/css/style.css#grid-canvas-css]
<<< @/../website/index.html#grid-canvas-markup [website/index.html#grid-canvas-markup]
:::
