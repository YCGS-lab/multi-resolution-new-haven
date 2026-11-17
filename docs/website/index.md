# Map viewer

`website/` is a static site, named **Bowerbird** in its header and page
title: `index.html`, a stylesheet, sixteen ES modules in `js/`, and the
vendored bundles in `vendor/` (deck.gl and deck.gl-raster, the COG decoder
worker, zarrita). There is no server-side code and no build step for the
application code: the browser loads the modules as they are. At start-up it
fetches `env.json` (see [Where the website runs](./time#where-the-website-runs-and-credentials))
and `catalog.json` (see [Website data and the catalog](/pipeline/website-data));
after that it draws every image itself, tile by tile.

## Modules

```mermaid
flowchart TD
  main["main.js<br/>start-up, tabs, URL"]
  catalog["catalog.js<br/>catalog, coordinates"]
  location["location.js<br/>place, search, tools"]
  viewer["viewer.js<br/>one map + compare"]
  grid["grid.js<br/>synchronized grid"]
  animation["animation.js<br/>animation tab"]
  icesat2["icesat2.js<br/>ICESat-2 profiles"]
  picker["picker.js<br/>image menu"]
  tc["timecontrol.js<br/>time controls"]
  slot["slot.js<br/>one map's selection"]
  time["time.js<br/>timesteps in view"]
  mapview["mapview.js<br/>view states, map chrome"]
  tiles["tiles.js<br/>layers; live sources"]
  cog["cog.js<br/>COG layers, shaders"]
  zarr["zarr.js<br/>ARCO Zarr grids"]
  vendor[["vendor/deck-gl-raster.js"]]
  worker[["vendor/geotiff-worker.js"]]
  zarrita[["vendor/zarrita.js"]]
  main --> catalog & location & viewer & grid & animation & icesat2
  viewer & grid & animation --> picker & slot
  viewer & grid --> tc
  slot --> time
  viewer & grid & animation & icesat2 --> mapview --> tiles --> cog --> vendor
  tiles --> zarr -.->|"on first use"| zarrita
  cog -.->|"decoder pool"| worker
```

All map modules import deck.gl from `vendor/deck-gl-raster.js` (deck.gl 9.4
and deck.gl-raster 0.8.1 in one file), and most import `env.js`; only the
main chain is drawn.

| Module | Role | Page |
|---|---|---|
| `main.js` | Loads `env.json` and the catalog, builds the tabs, syncs state with the URL, keyboard shortcuts | [Page, picker and URL state](./page) |
| `env.js` | Where the site runs (`env.json`: cloud or local, service URLs), the user's API keys and the credentials dialog | [Time, live data and credentials](./time#where-the-website-runs-and-credentials) |
| `catalog.js` | The `Catalog` class: product tree, lookups, coordinate conversions | [Catalog and coordinates](./catalog) |
| `location.js` | The selected place, the place search box and the location tools menu | [Place search and location tools](./search) |
| `viewer.js` | The Viewer tab: one map, optional comparison (swipe, opacity, spy) | [Viewer, compare and grid](./viewer-and-grid) |
| `grid.js` | The Grid tab: many maps with shared pan/zoom on one WebGL canvas | [Viewer, compare and grid](./viewer-and-grid#one-canvas-for-the-grid) |
| `animation.js` | The Animation tab: frames loaded ahead of time, played back | [Time, live data and credentials](./time#animation-tab) |
| `icesat2.js` | The ICESat-2 location tool: beam passes on a map and a photon cross-section | [Time, live data and credentials](./time#icesat-2-profiles-a-location-tool) |
| `picker.js` | The searchable image menu | [Page, picker and URL state](./page#the-image-picker) |
| `slot.js` | One map's selection (product, time, options) and why it cannot be shown | [Time, live data and credentials](./time#one-map-s-selection-slot) |
| `timecontrol.js` | The time controls under a map's picker: drop-down, calendar, month grid | [Time, live data and credentials](./time#the-time-control) |
| `time.js` | Timestep keys, and which timesteps have data over the area in view | [Time, live data and credentials](./time#which-timesteps-have-data-in-view) |
| `mapview.js` | View-state conversion, zoom limits, compare-mode props, the place marker, axes, scale bar, colorbars, loading messages | [Map views](./map-views) |
| `tiles.js` | Turns a product into deck.gl layers; image services, tilers and XYZ map tiles | [Image-service layers](./image-services) |
| `cog.js` | COG layers with deck.gl-raster; render spec → shader | [COG layers](./cog-layers) |
| `zarr.js` | ERA5-Land hours read from ARCO Zarr stores with zarrita | [Time, live data and credentials](./time#era5-land-from-an-arco-zarr-store) |

## How a map gets drawn

A product is a list of layers (from the catalog). Each layer becomes one
deck.gl layer, chosen by its source type:

```mermaid
flowchart LR
  P["product<br/>(layers bottom to top)"] --> L{"source type"}
  L -->|cog| C["FinerCOGLayer<br/>(deck.gl-raster)"]
  L -->|"arcgis, pc-mosaic,<br/>titiler-cmr, tiler"| A["TileLayer → BitmapLayer<br/>tiles colored on the CPU"]
  L -->|xyz| X["TileLayer → BitmapLayer<br/>map tiles as they come"]
  L -->|zarr| Z["BitmapLayer<br/>the hour's grid, colored on the CPU"]
  C --> GPU["GPU: generated shader<br/>colors each screen pixel"]
```

The live sources (ArcGIS ImageServers, Planetary Computer mosaics,
titiler-cmr and this repository's tiler) mostly send raw values: float
images or NumPy (NPY) tiles (NAIP comes as 8-bit images). `tiles.js` colors
them on the CPU with the same render specs and keeps them in one tile cache;
see [Image-service layers](./image-services) and
[Live sources](./time#live-sources).

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
4. **Image services and tilers are read live**, their raw tiles colored on
   the CPU with the same render specs. → [Image-service layers](./image-services)
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
