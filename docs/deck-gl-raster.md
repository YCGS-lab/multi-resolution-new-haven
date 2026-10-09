# COG rendering with deck.gl-raster

The website's maps used to read the local Cloud-Optimized GeoTIFFs with
[geotiff.js](https://geotiffjs.github.io/) and color every tile on the CPU
(`website/js/tiles.js`). They now use
[deck.gl-raster](https://github.com/developmentseed/deck.gl-raster) by
Development Seed (`@developmentseed/deck.gl-geotiff` `COGLayer`, **v0.8.1**,
released 2026-09-23) to read the COGs and draw them on the GPU. This document
covers how that was done, what it removed, what the website still implements
itself, how the two versions compare, and how to update deck.gl-raster.

deck.gl-raster is in beta and changes quickly (v0.6 → v0.8.1 in five months,
with breaking changes in most minor releases). Its documentation site lags
the code, so the API used here was read from the **source of the v0.8.1 tag**
(`packages/deck.gl-geotiff/src/cog-layer.ts`,
`packages/deck.gl-raster/src/raster-tile-layer/`, `.../gpu-modules/`,
`packages/geotiff/src/`), with the docs and examples only as a guide.

**Contents:** [Process](#process) · [Architecture](#architecture) ·
[Removed](#what-was-removed) · [Still implemented here](#what-the-website-still-implements) ·
[Upstream issues](#upstream-issues-found) · [Performance](#performance) ·
[Updating](#updating-deck-gl-raster)

## Process

1. **Read the release source.** Cloned the repository, checked out `v0.8.1`,
   and read `COGLayer` → `RasterTileLayer` → `RasterTileset2D` (tile
   traversal) → `RasterLayer` / `MeshTextureLayer` (rendering), the GPU
   modules, and the `@developmentseed/geotiff` reader (fetch, decoders, worker
   pool). Findings that shaped the design:
   - `COGLayer` takes custom `getTileData(image, {device, x, y, signal, pool})`
     and `renderTile(data) → {renderPipeline}` callbacks; the default pipeline
     only handles unsigned-integer COGs (not our float32 LERC data).
   - Rendering is a *pipeline of shader modules* injected into
     `DECKGL_FILTER_COLOR`. Pipelines are compared by **module name**, so
     modules with different code need different names.
   - Tiles are placed in deck.gl *Web Mercator common space*, and tile
     selection assumes a `WebMercatorViewport` (or `GlobeViewport`). There is
     no `OrthographicView` support, which the website used.
2. **Build test data.** The real COGs need credentials for most datasets, so
   the comparison used the ones that build without them (Landsat L2: 7-band
   LERC float; GOES LST; PRISM; the 0.5 m CT impervious-surface classes, a
   40 MB uint8 DEFLATE COG) plus `scripts/website/benchmark/fixtures.py`,
   which writes COGs exercising every other render path: a JPEG COG (like
   Planet), a DEM with a stored hillshade (like ASTER), a log color scale (like
   VIIRS night lights), uint8 DEFLATE classes (like the impervious surfaces),
   sparse points with `dilate_px` over a basemap (like ICESat-2), and band
   expressions (like NISAR).
3. **Probe the reader in the browser** (the package needs `DOMParser`, so not
   in Node): which layout each of our COGs decodes to. This found the
   multi-band LERC issue below.
4. **Implement** (below), then **compare** every product against the original
   site screenshot by screenshot (headless Chromium, both versions served side
   by side over the same `catalog.json` and `image-data/`), including the
   compare modes, the grid, and deep zoom; then **benchmark** (see
   [Performance](#performance)).

## Architecture

```
website/
  vendor/                       built by scripts/website/vendor (committed)
    deck-gl-raster.js           deck.gl 9.4 + deck.gl-raster 0.8.1, one ES module
    geotiff-worker.js           tile decoder worker (LERC, DEFLATE, JPEG, ...)
    lerc-wasm.wasm              LERC decoder
    versions.json               every package version in the bundle
  js/cog.js                     COG layers: tile upload + render spec → GLSL
  js/tiles.js                   per product layer: COGLayer, ArcGIS or XYZ TileLayer
  js/mapview.js                 view-state conversion, compare-mode props
```

- **Bundle instead of CDN.** deck.gl-raster is an npm ES-module package with
  deck.gl as a peer dependency. Loading it next to the deck.gl UMD build from
  unpkg would give two copies of deck.gl/luma.gl, which do not work together.
  `scripts/website/vendor/build.mjs` (esbuild, exact versions in
  `package.json` + `package-lock.json`) bundles deck.gl and deck.gl-raster
  into `website/vendor/`, which is committed so the site still needs no build
  step to serve or deploy. The decoder worker and the LERC wasm are separate
  files the bundle loads by URL.
- **MapView.** The maps now use deck.gl's `MapView`. The pan/zoom limits,
  axes, scale bar and URL state keep working in "world" coordinates (EPSG:3857
  meters from the extent center, `2^zoom` px per meter);
  `toDeckViewState` / `fromDeckViewState` in `mapview.js` convert at the
  deck.gl boundary (MapView zoom = world zoom + log2(40075016.7 / 512)).
  Other layers (landmarks, background, spy lens) use longitude / latitude.
- **One deck.gl layer per product layer.** Previously each product was one
  `TileLayer` whose tiles composited all its layers on the CPU. Now a COG
  layer is a `COGLayer`, an ArcGIS layer a `TileLayer` of CPU-colored bitmaps,
  and an XYZ layer a plain `TileLayer` of map tiles; deck.gl composites them.
- **COG layers** (`cog.js`):
  - One `GeoTIFF` per URL (`GeoTIFF.fromUrl`, a 6-per-origin request limiter)
    is shared by every layer and grid slot on that COG; the layer is added
    when its header is read (`onCogOpened`).
  - `getTileData` fetches the tile (`image.fetchTile`, decoded in the worker
    pool), keeps the bands the render spec reads, marks no data, and uploads
    them as one `r32float` / `rg32float` / `rgba32float` texture (8-bit RGB
    imagery as `rgba8unorm`), nearest-neighbor sampled. All-no-data tiles
    return `null` and are not drawn.
  - `renderTile` returns a single shader module **generated from the render
    spec**: band expressions are translated to GLSL; linear / log stretches with
    gamma; 256-color colormaps as a lookup texture with under / over colors;
    categorical codes as a lookup texture; multiplying by a stored hillshade;
    and `dilate_px` as a search of neighboring screen pixels. Each spec gets a
    uniquely named module (see the pipeline-name note above).
- **Compare modes.** Swipe uses `ClipExtension`, but its bounds are in each
  layer's coordinates: longitude / latitude for ordinary layers, common space
  for the COG meshes, and the mesh layer needs `clipByInstance: false`
  (`overlayProps` in `mapview.js`). Spy (`MaskExtension`) and opacity work
  unchanged.

## What was removed

| Removed | Replaced by |
|---|---|
| geotiff.js 2.1.3 from jsDelivr (COG reading, and the ArcGIS float TIFFs) | `@developmentseed/geotiff` in the bundle |
| deck.gl 9.4.0 UMD from unpkg | the bundle (same deck.gl version) |
| `CogSource`: opening COGs, picking the overview, windowed `readRasters`, no-data masking | `COGLayer`: overview choice by screen resolution (device-pixel aware), tile fetch with range requests and a request limiter, decoding in a worker pool (geotiff.js decoded LERC on the main thread), texture lifetime |
| CPU colorizing of COG data (stretches, expressions, colormaps, categorical, shading) | GPU shader modules generated per render spec |
| `resample` (nearest-neighbor resampling of colors onto 512-px tiles) | GPU texture sampling; native pixel edges now land exactly where the geotransform puts them (the old tiles snapped them to tile pixels, off by up to ~17 screen px at the deepest zoom) |
| `dilate`, `crop`, `over` (CPU dilation and compositing) | GPU dilation in the shader; deck.gl compositing of separate layers |
| `XyzSource`, its tile cache, mosaicking and `resampleSmooth` | a standard deck.gl `TileLayer` of the map tiles (desaturation via `BitmapLayer`, lightening as a white veil layer) |
| `readSparseTiles` (hand-written reader for ArcGIS sparse float TIFFs) | `fetchTile` per TIFF tile, sparse tiles skipped |
| decoding and coloring on the main thread | decoding in workers, coloring on the GPU |

The application JavaScript did **not** get shorter: `website/js/` went from
1,861 to 2,150 lines. About 450 lines of reader, resampling, compositing and
XYZ code went; `cog.js` (390 lines, mostly the render-spec → GLSL compiler and
tile upload) and the MapView conversions came in. The win is in *where* the
work runs and in correctness, not in code size.

## What the website still implements

deck.gl-raster provides the reading and tiling; the rest is ours:

- **Render specs → shaders.** deck.gl-raster ships `CreateTexture`,
  `LinearRescale`, `Colormap` (a sprite of named colormaps), `FilterNoDataVal`,
  `CompositeBands`, `MaskTexture`. They were not used:
  - `Colormap` overwrites the whole color, so it cannot do under / over
    colors, `extend`, gamma, log scales, or keep no-data transparent; our
    colormaps are arbitrary 256-color lists from matplotlib, not the named
    sprite.
  - `LinearRescale` applies one range to all channels (ours are per channel,
    with gamma), and nothing evaluates band expressions.
  - `FilterNoDataVal` compares one exact value; our LERC data are lossy, so
    no data is "below -9000", and expressions need every band they read.
  - `dilate_px` must sample neighbors, so our module samples its own texture
    instead of following `CreateTexture`.
- **Tile upload** (`getTileData`): band selection, multi-band LERC unpacking
  and edge-tile clipping (see the issues below), no-data marking, packing up
  to four bands per texture. The default pipeline handles only unsigned-integer
  COGs.
- **EPSG:3857 definition.** The default `epsgResolver` fetches projections
  from epsg.io at runtime; `cog.js` resolves EPSG:3857 locally.
- **ArcGIS ImageServer layers** (CT orthoimagery, NAIP, CT lidar, 3DEP) still
  go through the CPU renderer in `tiles.js` (`exportImage` per tile, colored
  on the CPU, including the hillshades computed from the lidar / 3DEP
  elevations). They could move to deck.gl-raster's `RasterTileLayer` with a
  Web Mercator tileset and the same shader modules; a GPU hillshade needs a
  one-pixel border around each tile, which `RasterTileLayer`'s tile-to-texture
  mapping does not provide yet.
- **Hillshades computed in the browser for COGs** are not supported by the GPU
  path (no COG uses them: ASTER stores its hillshade as a band). `cog.js`
  throws a clear error if a spec asks for one.
- **Compare-mode plumbing** (clip bounds per coordinate system, see above).

### Behavior differences

- `dilate_px` is now exactly that many **device pixels**; the CPU renderer
  grew pixels by that many *tile* pixels (0.7–1.4 screen pixels each), so
  points look somewhat larger (e.g. tracks ~8 px instead of ~5 px wide at
  1x). Growth stops at COG tile edges (512 source pixels), where the CPU
  renderer read across them; it no longer drops points between tiles, which
  the old nearest-neighbor tile resampling sometimes did.
- High-frequency data seen zoomed out (the impervious-surface classes at the
  full extent) differ pixel by pixel: both renderers nearest-sample an
  overview about twice as fine as the screen, at a different phase. Neither
  is systematically different once the overview choice matches (issue 3).
- In **opacity** compare mode, a multi-layer product (ICESat-2: basemap plus
  points) is now faded layer by layer rather than as one composited image.
- The lightened, desaturated basemap uses deck.gl's luminance weights for
  desaturation.
- deck.gl-raster's mesh layer logs `luma.gl: Binding sampler not set: Not found
  in shader layout.` once per layer (its vendored `SimpleMeshLayer` shader drops
  the `sampler` uniform that `SimpleMeshLayer` still binds). It is harmless.

## Upstream issues found

Worth reporting to deck.gl-raster (all worked around in `cog.js`):

1. **Multi-band, pixel-interleaved LERC decodes to one array.** GDAL writes
   such tiles as one LERC blob with the bands as "depth"; `lerc.decode` returns
   one array holding every band in turn, and `codecs/lerc.ts` returns it as
   `{layout: "band-separate", bands: [that array]}` while `count` is the band
   count. Consumers indexing `bands[i]` get `undefined` for `i > 0`.
2. Because of (1), `fetchTile(..., {boundless: false})` **clips only the first
   band's rows** on edge tiles of such COGs. `cog.js` fetches boundless tiles
   and clips them itself.

3. **Overviews up to 2x too coarse.** The tile traversal's
   `getMetersPerPixel(lat, zoom)` divides by `2^(zoom + 8)`, i.e. a 256-px
   world (the OSM convention, as `dev-docs/lod-and-pixel-matching.md` says), but
   deck.gl's `viewport.zoom` is for a 512-px world. Screen pixels are taken to
   be twice their real size, so the "coarsest overview not coarser than a
   screen pixel" is up to twice as coarse as the screen. (It also compares
   source pixels in CRS units, Web Mercator meters for us, against screen
   pixels in ground meters, which leans 1/cos(lat) = 1.33x finer here.) On the
   0.5 m impervious-surface COG at the full extent it read the 21.3 m overview
   where the old renderer read 10.65 m, and thin roads vanished from the
   mode-resampled overview. `FinerCOGLayer` in `cog.js` doubles the pixel ratio
   the traversal uses, by wrapping the tileset's (private) `getPixelRatio`;
   overview choice then matches the old renderer.

Also of note: `GeoTIFF.fromArrayBuffer` and the reader need browser APIs
(`DOMParser`), so tests of the reader have to run in a browser.

## Performance

PERFORMANCE_PLACEHOLDER

## Updating deck.gl-raster

Releases are frequent and often breaking, so treat each update as a small
migration:

1. **Read what changed, in the source.** Check
   [CHANGELOG.md](https://github.com/developmentseed/deck.gl-raster/blob/main/CHANGELOG.md)
   and the diff of the packages we use between our tag and the new one, e.g.

   ```sh
   git clone https://github.com/developmentseed/deck.gl-raster && cd deck.gl-raster
   git diff v0.8.1 v0.9.0 --stat -- packages/deck.gl-geotiff packages/deck.gl-raster packages/geotiff
   git diff v0.8.1 v0.9.0 -- packages/deck.gl-geotiff/src/cog-layer.ts \
     packages/deck.gl-raster/src/raster-tile-layer packages/deck.gl-raster/src/mesh-layer \
     packages/geotiff/src/fetch.ts packages/geotiff/src/codecs/lerc.ts packages/geotiff/src/geotiff.ts
   ```

   What `cog.js` depends on: `COGLayer` props (`geotiff`, `epsgResolver`,
   `pool`, `getTileData(image, {device, x, y, signal, pool})`, `renderTile`
   returning `{renderPipeline: [{module, props}]}`, `onTileUnload`,
   `maxRequests`, `refinementStrategy`); `GeoTIFF.fromUrl(url,
   {concurrencyLimiter})`, `GeoTIFF.fromArrayBuffer`, `fetchTile(x, y,
   {boundless, pool, signal})` and its `RasterArray` result;
   `image.width/height/tileWidth/tileHeight`, `cachedTags`; `DecoderPool({createWorker})`,
   `PerOriginSemaphore`, `parseWkt`; the shader injection hook
   `fs:DECKGL_FILTER_COLOR` with `geometry.uv`, and pipelines compared by module
   name; and, for `FinerCOGLayer`, that `COGLayer.renderLayers()` returns a
   `TileLayer` whose `TilesetClass` is a `RasterTileset2D` with a
   `getPixelRatio` field (it throws if that field is gone). Check whether the
   upstream issues above are fixed: then the workarounds (`bandArrays` /
   `clip`, `FinerCOGLayer`) can go; for (3), compare which overview each
   version reads, e.g. by logging `image.width` in `getTileData`. Also check
   whether new GPU modules could replace parts of the generated shader.
2. **Bump the versions** in `scripts/website/vendor/package.json` (all
   `@developmentseed/*` packages to the same version; deck.gl to the version
   their `peerDependencies` ask for), then

   ```sh
   cd scripts/website/vendor
   npm install            # updates package-lock.json
   npm run build          # rewrites website/vendor/
   ```

   Check `website/vendor/versions.json` in the diff: one version of each of
   `@deck.gl/*`, `@luma.gl/*` and `@developmentseed/*`.
3. **Fix the website code** for API changes (mainly `website/js/cog.js`, and
   `scripts/website/vendor/entry.js` if exports moved).
4. **Test against the previous version** in a browser, with the COGs built
   (`just build` or the datasets you have) and the fixtures:

   ```sh
   uv run scripts/website/benchmark/fixtures.py && uv run scripts/website/build_catalog.py
   git worktree add ../newhaven-before main          # the version to compare with
   ln -s "$PWD/website/image-data" ../newhaven-before/website/image-data
   ln -s "$PWD/website/catalog.json" ../newhaven-before/website/catalog.json
   (cd ../newhaven-before && uv run scripts/website/serve.py --port 8001) &
   uv run scripts/website/serve.py --port 8000 &
   ```

   Look through the products at http://localhost:8000/website/ next to
   http://localhost:8001/website/ (each render type, the compare modes, the
   grid, deep zoom) and watch the console for errors. Then run the benchmark:

   ```sh
   cd scripts/website/benchmark && npm ci
   node bench.mjs --runs 5 --out before-after.json \
     before=http://localhost:8001/website/ after=http://localhost:8000/website/
   node bench.mjs --runs 5 --latency 40 before=... after=...
   ```

   (`CHROME=/path/to/chrome` if Playwright's Chromium is elsewhere.)
5. **Commit** `package.json`, `package-lock.json`, `website/vendor/`, the code
   changes, and the version and any new findings in this document.
