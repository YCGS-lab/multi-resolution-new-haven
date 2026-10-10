# COG layers (deck.gl-raster)

`website/js/cog.js` draws the local COGs. It is the core of the renderer
migration and holds most of the website's non-obvious code. Read this page
closely.

## Who does what

[deck.gl-raster](/guide/glossary#deck-gl-raster)'s `COGLayer` does the
generic work. `cog.js` adds what is specific to this project's render specs.

| deck.gl-raster (v0.8.1) | `cog.js` |
|---|---|
| Reads the COG header; lists its overview levels | Opens each COG once and shares it ([below](#opening-cogs)) |
| Picks the overview level and the tiles visible in the viewport | Corrects the level choice ([FinerCOGLayer](#finercoglayer-overviews-as-fine-as-the-screen)) |
| Fetches tiles with range requests, limited per origin | Sets the limit ([below](#workers-and-request-limits)) |
| Decodes LERC, JPEG and DEFLATE in a worker pool | Provides the worker ([build](/build/vendor)) |
| Draws each tile as a mesh, with a texture and a pipeline of shader modules | Uploads the bands a spec needs ([tile upload](#tile-upload)); generates the shader module ([render spec → GLSL](#render-spec-to-glsl)) |
| Caches tiles; calls `onTileUnload` when one is evicted | Frees its textures |

`COGLayer`'s default pipeline handles only unsigned-integer COGs, which it
shows as images. Our COGs are mostly float32 measurements colored by render
specs. So each layer supplies its own `getTileData` (load a tile into GPU
textures) and `renderTile` (return the shader modules that color it).

## Creating the layer

::: code-group
<<< @/../website/js/cog.js#cog-layer [website/js/cog.js#cog-layer]
:::

- **`program`**: the compiled render spec, cached per layer spec: the bands
  to upload, the texture kind, the shader module, and an optional lookup
  table ([below](#render-spec-to-glsl)).
- **`getTileData`**: wraps the tile load with the map's
  [loading state](./map-views#loading-state). It returns `null` on failure
  (and on abort, when deck.gl cancels a tile that scrolled out of view), so
  one bad tile does not break the layer.
- **`renderTile`**: always the same single module, given this tile's
  textures.
- **`refinementStrategy: "no-overlap"`**: while finer tiles load, coarser
  ones are not drawn underneath. Products with transparent pixels (sparse
  points, no-data areas) would otherwise show stale coarse pixels through
  the gaps. The old renderer used the same setting.
- **`onTileUnload`**: destroys the tile's textures. deck.gl-raster does this
  only for its default pipeline.
- **`props`**: clip, mask or opacity settings from the compare modes
  ([viewer](./viewer-and-grid#comparison-props-per-coordinate-system)).

## Opening COGs <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/cog.js#open-cogs [website/js/cog.js#open-cogs]
:::

One `GeoTIFF` (the parsed header) per URL, shared by every layer that uses
the file. The five Landsat products and any grid slots showing them all use
one header. `COGLayer` accepts a URL or an opened `GeoTIFF`. Passing the URL
would be simpler, but each layer would then fetch and parse the header
again.

Opening is asynchronous, but deck.gl layers are created synchronously on
every render. While a file is opening, `cogLayer` returns `null` and the
product is drawn without that layer. When the header arrives,
`onCogOpened` listeners redraw: `main.js` registers the Viewer and the Grid.

## Workers and request limits <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/cog.js#pool-and-limiter [website/js/cog.js#pool-and-limiter]
:::

- **Decoder pool.** Tiles are decoded in Web Workers, one per CPU core, off
  the main thread. The worker script is a separate file in `website/vendor/`.
  It loads the LERC WebAssembly module from next to itself.
- **Request limit.** deck.gl-raster makes one range request per 512 × 512
  tile. That is many more, smaller requests than the old reader, which read
  large blocks. Browsers allow 6 concurrent HTTP/1.1 connections per origin,
  so the limit is 6. Over HTTP/2 or HTTP/3 (CloudFront serves both),
  requests share one connection and the limit is raised to 24. The protocol
  is read from the page's own navigation entry.

::: warning Not measured
The benchmark ran over local HTTP/1.1. The HTTP/2 limit of 24 is a
reasoned guess. With 40 ms of latency per request, zooming into the 0.5 m
impervious-surface COG was 1.76× slower than the old reader at 6 requests;
see [Performance](/comparison/performance).
:::

## Projection

::: code-group
<<< @/../website/js/cog.js#epsg-resolver [website/js/cog.js#epsg-resolver]
:::

deck.gl-raster reprojects any CRS on the GPU. To learn a CRS from its EPSG
code, its default resolver fetches the definition from epsg.io at run time.
All of our COGs are EPSG:3857, so `cog.js` answers locally and refuses any
other code. That means no request to a third-party site, and no failure if
it is down.

## Tile upload

`getTileData` calls `loadTile`:

::: code-group
<<< @/../website/js/cog.js#load-tile [website/js/cog.js#load-tile]
:::

1. Fetch and decode tile (x, y) of the chosen overview level (`image`).
2. Split the result into one array per band, and clip edge tiles to the
   image ([below](#workaround-multi-band-lerc)).
3. Keep only the bands the render spec reads, in the order the shader
   expects.
4. Upload them as one texture:
   - 8-bit RGB imagery (JPEG COGs): `rgba8unorm` with alpha 255.
   - Everything else: float32, one channel per band (`r32float`,
     `rg32float`, or `rgba32float` for 3–4 bands). No-data values become
     −3·10³⁸ (`NODATA_GPU`).
5. Tiles with no data at all return `null` and are not drawn.

All textures use **nearest-neighbor sampling**, so native pixels are drawn
as sharp blocks at any zoom. This is also the only option: float32 textures
cannot be filtered linearly in WebGL 2 without an extension.

::: warning Design decision: a sentinel for no data
The obvious choice, NaN, is unreliable in shaders: GLSL compilers may
optimize `isnan(x)` or `x != x` away. Instead, no data is a huge negative
number that no real value reaches, tested as `v > -1e38`. COGs store no
data as −9999, and LERC is lossy, so the source test is loose: below
−9000 counts as no data.
:::

### Workaround: multi-band LERC <Badge type="danger" text="workaround" />

::: code-group
<<< @/../website/js/cog.js#band-arrays [website/js/cog.js#band-arrays]
<<< @/../website/js/cog.js#clip [website/js/cog.js#clip]
:::

::: danger deck.gl-raster 0.8.1 bug
GDAL writes a multi-band, pixel-interleaved LERC tile as one LERC blob with
the bands as "depth". The `lerc` decoder returns one array holding every band
in turn. deck.gl-raster labels it band-separate with a single band, while
`count` says 7 (Landsat). `bandArrays` splits it. For the same reason the
library's own edge-tile clipping (`boundless: false`) would clip only the
first band's rows. So tiles are fetched unclipped (`boundless: true`), and
`clip` cuts each band to the part inside the image.
:::

## Render spec to GLSL

`compile` turns one layer's [render spec](/pipeline/website-data#render-specs)
into a deck.gl-raster shader module. The module is GLSL source code
generated as a string, with the spec's constants (ranges, gamma, colors)
written in as literals.

::: warning Design decision: generate one shader per spec
deck.gl-raster offers ready-made modules (`LinearRescale`, `Colormap`,
`FilterNoDataVal`, ...), but none fits the render specs. Their limits, and
how the generated module handles each case, are compared in
[Coloring](/comparison/coloring#why-not-deck-gl-raster-s-modules). The
generated code is short and specific: only the operations the spec uses,
with its numbers as constants.

Two details are forced by how deck.gl-raster composes modules:
- **Unique names.** deck.gl-raster decides whether to recompile a layer's
  shader by comparing module *names*. Every compiled spec gets a new name
  (`cogRender<n>`), with matching uniform names (`cogBands<n>`, ...).
- **Own texture sampling.** The module samples the tile texture itself,
  rather than taking the color from deck.gl-raster's `CreateTexture`
  module, because `dilate_px` must read neighboring pixels.
:::

The shared skeleton: each module declares its textures and a function
`cogColor<n>(uv)` that reads the texel `v` at `uv` and returns a color `c`
(alpha 0 = transparent). Transparent pixels are discarded.

::: code-group
<<< @/../website/js/cog.js#shader-module [website/js/cog.js#shader-module]
:::

### Bands and values

::: code-group
<<< @/../website/js/cog.js#compile-bands [website/js/cog.js#compile-bands]
:::

The spec's bands get texture channels `r`, `g`, `b`, `a` in order of first
use. A layer can read at most 4 bands. `value()` gives two GLSL
expressions: the value (`v.r`, or a translated expression) and an `ok` test
(every band it reads has data).

::: code-group
<<< @/../website/js/cog.js#glsl-expr [website/js/cog.js#glsl-expr]
:::

Band expressions are translated from JavaScript syntax to GLSL token by
token:
- Band names become texture channels, and `log10` becomes a helper (GLSL has
  no `log10`).
- Integer literals become floats (`10` → `10.0`), because GLSL does not mix
  int and float.
- Anything else (unknown names, `**`, other characters) is rejected with an
  error. An expression is never executed as code.

::: code-group
<<< @/../website/js/cog.js#normalize-glsl [website/js/cog.js#normalize-glsl]
:::

Normalization matches the CPU renderer's `normalizer` (in `tiles.js`): linear
or log, then the gamma power, applied only strictly between 0 and 1.

### The four render types

::: code-group
<<< @/../website/js/cog.js#compile-identity [website/js/cog.js#compile-identity]
<<< @/../website/js/cog.js#compile-rgb [website/js/cog.js#compile-rgb]
<<< @/../website/js/cog.js#compile-colormap [website/js/cog.js#compile-colormap]
<<< @/../website/js/cog.js#compile-categorical [website/js/cog.js#compile-categorical]
:::

- **identity**: the texel as RGB, optionally desaturated and lightened.
- **rgb**: each channel normalized and clamped; transparent unless all three
  have data.
- **colormap**: normalize, then pick one of 256 colors from a 256 × 1 lookup
  texture, or the under/over color outside 0–1. A stored hillshade band
  then multiplies the color by `1 − s + s·hs`.
- **categorical**: the value as an integer code 0–255, looked up in a 256 × 1
  table; codes not in the spec are transparent.

Lookups use `floor(t × 256)` and sample the texel center, so colors match
the CPU renderer's `colors[floor(t × N)]` exactly. There is no blending
between neighboring colors.

::: code-group
<<< @/../website/js/cog.js#lut [website/js/cog.js#lut]
:::

### dilate_px

`dilate_px` grows data pixels into transparent screen pixels, to keep sparse
points visible ([ICESat-2](/pipeline/datasets/vegetation-and-land-cover#rasterizing-footprints)):

::: code-group
<<< @/../website/js/cog.js#dilate-shader [website/js/cog.js#dilate-shader]
:::

For a transparent pixel, the shader looks at screen-pixel offsets (from
`dFdx`/`dFdy`, the change in texture coordinates per screen pixel) up to `R`
pixels away. It tries the same row first, nearest first, then the nearest
rows. That is the same order as the CPU renderer's two passes (horizontal,
then vertical), so the same neighbor wins.

::: code-group
<<< @/../website/js/cog.js#occupancy [website/js/cog.js#occupancy]
:::

::: warning Design decision: skip empty areas
Most screen pixels in a sparse product are far from any data. Searching
around each of them costs up to 48 texture reads. On upload, each tile gets
a small *occupancy* texture: one texel per 8 × 8 block, set if that block
or a neighbor has data. A transparent pixel reads it once and skips the
search if nothing is within 8 texels. When the search radius exceeds 8
texels (zoomed far out), the shortcut is not used.
:::

::: warning Behavior differences
- `dilate_px` is now in **device pixels**. The CPU renderer grew pixels by
  *tile* pixels, which are 0.7–1.4 screen pixels, so points now look somewhat
  larger.
- The search cannot see across tile edges, so growth stops at a COG tile
  boundary. The CPU renderer read across them.
- Under software rendering (SwiftShader) the loop is slow even with the
  shortcut. Real GPUs branch per pixel group and should skip it, but this is
  not measured.
:::

## FinerCOGLayer: overviews as fine as the screen <Badge type="danger" text="workaround" />

::: code-group
<<< @/../website/js/cog.js#finer-cog-layer [website/js/cog.js#finer-cog-layer]
:::

::: danger deck.gl-raster 0.8.1 bug
To choose an overview, the tile traversal compares a source pixel's size
with a screen pixel's size in meters. It computes the screen pixel as if
deck.gl's world were 256 pixels wide at zoom 0 (the OpenStreetMap
convention), but deck.gl's is 512. Screen pixels count as twice their size,
so the traversal accepts overviews up to twice as coarse as the screen. On
the 0.5 m impervious-surface COG, it read the 21.3 m overview where the old
renderer read 10.65 m, and thin roads disappeared.

`FinerCOGLayer` takes the `TileLayer` that `COGLayer` builds and substitutes
a subclass of its tileset class, whose `getPixelRatio` (the traversal's
device-pixel ratio) is doubled. This reaches into a private field. It
throws a clear error if the field disappears in an update; see
[Updating deck.gl-raster](/deck-gl-raster#updating-deck-gl-raster).
:::

## What is not supported

- **Hillshades computed in the browser** (`hillshade: true`, or `shade`
  without `precomputed`). A per-pixel hillshade needs the neighbors of edge
  pixels, which are in the next tile. `compile` throws an error; COG
  datasets store their hillshade as a band instead (ASTER). The
  [ArcGIS path](./image-services#cpu-coloring) still computes hillshades,
  on the CPU.
- More than 4 bands in one layer, categorical codes outside 0–255, and
  CRSs other than EPSG:3857. Each raises a clear error.
