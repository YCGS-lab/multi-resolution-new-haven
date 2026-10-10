# Map viewer

`website/` is a static site: `index.html`, a stylesheet, eight ES modules in
`js/`, and the vendored deck.gl bundle in `vendor/`. There is no server-side
code and no build step for the application code: the browser loads the
modules as they are. At start-up it fetches `catalog.json` (see
[Website data and the catalog](/pipeline/website-data)); after that it draws
every image itself, tile by tile.

## Modules

```mermaid
flowchart TD
  main["main.js<br/>start-up, tabs, URL"]
  catalog["catalog.js<br/>catalog, coordinates"]
  viewer["viewer.js<br/>one map + compare"]
  grid["grid.js<br/>synchronized grid"]
  picker["picker.js<br/>image menu"]
  mapview["mapview.js<br/>view states, map chrome"]
  tiles["tiles.js<br/>layers; ArcGIS, XYZ"]
  cog["cog.js<br/>COG layers, shaders"]
  vendor[["vendor/deck-gl-raster.js"]]
  worker[["vendor/geotiff-worker.js"]]
  main --> catalog & viewer & grid
  viewer & grid --> picker
  viewer & grid --> mapview --> tiles --> cog --> vendor
  cog -.->|"decoder pool"| worker
```

All modules import deck.gl from `vendor/deck-gl-raster.js` (deck.gl 9.4 and
deck.gl-raster 0.8.1 in one file); only the main chain is drawn.

| Module | Role | Page |
|---|---|---|
| `main.js` | Loads the catalog, builds the Viewer and Grid, syncs state with the URL, keyboard shortcuts | [Page, picker and URL state](./page) |
| `catalog.js` | The `Catalog` class: product tree, lookups, coordinate conversions | [Catalog and coordinates](./catalog) |
| `viewer.js` | The Viewer tab: one map, optional comparison (swipe, opacity, spy) | [Viewer, compare and grid](./viewer-and-grid) |
| `grid.js` | The Grid tab: many maps with shared pan/zoom on one WebGL canvas | [Viewer, compare and grid](./viewer-and-grid#one-canvas-for-the-grid) |
| `picker.js` | The searchable image menu | [Page, picker and URL state](./page#the-image-picker) |
| `mapview.js` | View-state conversion, zoom limits, compare-mode props, landmarks, axes, scale bar, colorbars, loading messages | [Map views](./map-views) |
| `tiles.js` | Turns a product into deck.gl layers; ArcGIS and XYZ layers | [Image-service layers](./image-services) |
| `cog.js` | COG layers with deck.gl-raster; render spec → shader | [COG layers](./cog-layers) |

## How a map gets drawn

A product is a list of layers (from the catalog). Each layer becomes one
deck.gl layer, chosen by its source type:

```mermaid
flowchart LR
  P["product<br/>(layers bottom to top)"] --> L{"source type"}
  L -->|cog| C["FinerCOGLayer<br/>(deck.gl-raster)"]
  L -->|arcgis| A["TileLayer → BitmapLayer<br/>tiles colored on the CPU"]
  L -->|xyz| X["TileLayer → BitmapLayer<br/>map tiles as they come"]
  C --> GPU["GPU: generated shader<br/>colors each screen pixel"]
```

For a COG, one tile's journey:

```mermaid
sequenceDiagram
  participant D as deck.gl / COGLayer
  participant T as tile traversal
  participant G as getTileData (cog.js)
  participant W as decoder worker
  participant S as server (COG)
  participant F as fragment shader
  D->>T: viewport changed
  T->>T: pick overview level + visible tiles
  T->>G: load tile (x, y) of that level
  G->>S: HTTP range request for the tile's bytes
  S-->>G: compressed tile (LERC / JPEG / DEFLATE)
  G->>W: decode
  W-->>G: band arrays
  G->>G: keep the spec's bands, mark no data,<br/>upload as a float texture
  G-->>D: tile data (texture)
  D->>F: draw the tile's mesh with the<br/>render spec's shader module
  F->>F: per screen pixel: sample texture,<br/>stretch / colormap / shade / dilate
```

## Key design decisions

::: warning Decisions to review
1. **Each product layer is its own deck.gl layer**, composited by the GPU.
   The old renderer composited layers into one bitmap per tile on the CPU.
   → [Views and compositing](/comparison/views)
2. **COGs are read by deck.gl-raster and colored by shaders generated from
   the render specs.** → [COG layers](./cog-layers)
3. **`MapView` for deck.gl, "world" coordinates for everything else.**
   → [Map views](./map-views)
4. **Image services are read live**, ArcGIS tiles colored on the CPU with
   the same render specs. → [Image-service layers](./image-services)
5. **The grid draws all its maps on one canvas.**
   → [Viewer, compare and grid](./viewer-and-grid#one-canvas-for-the-grid)
6. **All state lives in the URL hash**, so any view can be linked.
   → [Page, picker and URL state](./page#state-in-the-url)
:::

::: tip Standard practice
The rest is ordinary DOM code without a framework: classes that own a piece
of the page, `innerHTML` templates with escaping, event listeners, and a
`requestAnimationFrame` throttle for redraws.
:::
