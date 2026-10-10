# Basemaps and image services

## XYZ map tiles

Before, the street maps went through the same per-tile pipeline as the data.
For each 512-px deck.gl tile, `XyzSource` picked a zoom so the labels came
out at about their design size, fetched the map tiles covering the tile
into an `OffscreenCanvas` mosaic (through its own cache of `ImageBitmap`s),
read the pixels back, colored them (desaturate, lighten) and resampled
them smoothly:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 169–220]
class XyzSource {
  constructor(spec) {
    this.spec = spec;
  }

  async read(box, res, bands, { signal } = {}) {
    const { url, tile_size: ts, max_zoom } = this.spec;
    // Map tiles are designed to be shown at 256 CSS pixels (512-pixel tiles are
    // the @2x versions): pick the zoom whose labels come out at about their
    // design size. A tile is shown at 0.5-1x its resolution `res`, and
    // res * 2^ZOOM_OFFSET is its size in CSS pixels at its own zoom.
    const zCss = Math.log2(CIRCUMFERENCE / (256 * res * 2 ** ZOOM_OFFSET)) - 0.5;
    const z = Math.max(0, Math.min(max_zoom, Math.round(zCss)));
    const span = CIRCUMFERENCE / 2 ** z;
    const O = CIRCUMFERENCE / 2;
    const tx0 = Math.floor((box[0] + O) / span);
    const tx1 = Math.floor((box[2] + O) / span - 1e-9);
    const ty0 = Math.floor((O - box[3]) / span);
    const ty1 = Math.floor((O - box[1]) / span - 1e-9);
    const width = (tx1 - tx0 + 1) * ts;
    const height = (ty1 - ty0 + 1) * ts;
    const canvas = new OffscreenCanvas(width, height);
    const ctx = canvas.getContext("2d");
    const jobs = [];
    for (let ty = ty0; ty <= ty1; ty++)
      for (let tx = tx0; tx <= tx1; tx++) {
        const src = url.replace("{z}", z).replace("{x}", tx).replace("{y}", ty);
        jobs.push(loadTile(src, signal).then((img) => img && ctx.drawImage(img, (tx - tx0) * ts, (ty - ty0) * ts, ts, ts)));
      }
    await Promise.all(jobs);
    const rgba = ctx.getImageData(0, 0, width, height).data;
    return { rgba, width, height, x0: tx0 * span - O, y1: O - ty0 * span, res: span / ts };
  }
}

const tileCache = new Map(); // url -> Promise<ImageBitmap | null>, oldest first

function loadTile(url, signal) {
  if (!tileCache.has(url)) {
    const p = fetch(url, { signal })
      .then((r) =>
        r.status === 404 ? null : r.ok ? r.blob().then(createImageBitmap) : Promise.reject(new Error(`${url}: HTTP ${r.status}`)),
      )
      .catch((e) => {
        tileCache.delete(url);
        throw e;
      });
    tileCache.set(url, p);
    if (tileCache.size > 600) tileCache.delete(tileCache.keys().next().value);
  }
  return tileCache.get(url);
}
```
:::

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 451–461]
/** Like resample, but with smooth (bilinear / mipmapped) scaling, for map tiles with text. */
function resampleSmooth(rgba, win, box, w, h) {
  const src = new OffscreenCanvas(win.width, win.height);
  src.getContext("2d").putImageData(new ImageData(rgba, win.width, win.height), 0, 0);
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  ctx.imageSmoothingQuality = "high";
  const sx = (box[0] - win.x0) / win.res;
  const sy = (win.y1 - box[3]) / win.res;
  ctx.drawImage(src, sx, sy, (box[2] - box[0]) / win.res, (box[3] - box[1]) / win.res, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h).data;
}
```
:::

After, the map tiles are drawn as they come. A deck.gl `TileLayer` with the
URL template and `tileSize: 256` gives about the same label size:

::: code-group
<<< @/../website/js/tiles.js#xyz-layers [website/js/tiles.js#xyz-layers]
:::

`MapView` and the tile services share the same Web Mercator tiling, so no
mosaicking or resampling is needed. deck.gl caches the tiles. Desaturation
is `BitmapLayer`'s option, and lightening is a translucent white layer on
top.

## ArcGIS float TIFFs

ArcGIS `exportImage` returns float TIFFs whose empty internal tiles have a
byte count of 0 ("sparse" tiles). geotiff.js could not read those, so the
old code had a reader for that one case:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 147–167]
/**
 * Band 1 of an uncompressed float32 tiled TIFF with sparse tiles (byte count 0,
 * as ArcGIS writes for tiles without data), which geotiff.js cannot read.
 */
function readSparseTiles(im, buf) {
  const fd = im.fileDirectory;
  if (fd.Compression !== 1 || fd.BitsPerSample[0] !== 32 || fd.SampleFormat?.[0] !== 3 || fd.SamplesPerPixel !== 1)
    throw new Error("sparse tiles are only supported for uncompressed single-band float32");
  const [W, H, tw, th] = [im.getWidth(), im.getHeight(), fd.TileWidth, fd.TileLength];
  const nx = Math.ceil(W / tw);
  const dv = new DataView(buf);
  const out = new Float32Array(W * H).fill(NaN);
  fd.TileOffsets.forEach((off, i) => {
    if (!fd.TileByteCounts[i]) return;
    const x0 = (i % nx) * tw;
    const y0 = Math.floor(i / nx) * th;
    for (let r = 0; r < th && y0 + r < H; r++)
      for (let c = 0; c < tw && x0 + c < W; c++) out[(y0 + r) * W + x0 + c] = dv.getFloat32(off + (r * tw + c) * 4, im.littleEndian);
  });
  return out;
}
```
:::

It was called only when sparse tiles were present; other TIFFs went through
geotiff.js's `readRasters`. Now that geotiff.js is gone, the bundled
`@developmentseed/geotiff` reads every internal tile, and sparse ones raise
"not found":

::: code-group
<<< @/../website/js/tiles.js#read-float-tiff [website/js/tiles.js#read-float-tiff]
:::

## ArcGIS tiles otherwise

The ArcGIS request and its CPU coloring are unchanged, apart from the tile
box. The old code got it from `OrthographicView` tiles in world meters; the
new code converts `MapView` tiles' longitude/latitude to Web Mercator
(`mercX`, `mercY`). Compare the old product layer:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 536–580]
/**
 * The deck.gl layer for a product. `loading` ({start(), end(error)}) is told
 * about each tile request; `props` (e.g. clip / mask extensions, opacity) go
 * to the tiles' bitmap layers.
 */
export function productLayer(id, catalog, product, { loading, props = {} } = {}) {
  const [ox, oy] = catalog.origin;
  // Street maps are magnified smoothly; data keep sharp pixels.
  const filter = product.layers.every((l) => catalog.sources[l.source].smooth) ? "linear" : "nearest";
  return new TileLayer({
    id,
    data: product.id, // a new product means new tiles
    tileSize: TILE_SIZE,
    zoomOffset: ZOOM_OFFSET,
    minZoom: -20,
    maxZoom: maxTileZoom(catalog, product),
    extent: catalog.extent,
    refinementStrategy: "no-overlap",
    maxRequests: 8,
    getTileData: async ({ bbox, signal }) => {
      const box = [bbox.left + ox, Math.min(bbox.top, bbox.bottom) + oy, bbox.right + ox, Math.max(bbox.top, bbox.bottom) + oy];
      loading?.start();
      try {
        const img = await renderTile(catalog, product, box, TILE_SIZE, TILE_SIZE, signal);
        loading?.end();
        return img;
      } catch (err) {
        loading?.end(signal?.aborted ? null : err);
        if (!signal?.aborted) console.warn(`${product.id}: tile failed`, err);
        return null;
      }
    },
    renderSubLayers: (p) => {
      if (!p.data) return null;
      const { left, right, top, bottom } = p.tile.bbox;
      return new BitmapLayer(p, {
        data: null,
        image: p.data,
        bounds: [left, Math.min(top, bottom), right, Math.max(top, bottom)],
        textureParameters: { minFilter: filter, magFilter: filter },
      });
    },
    ...props,
  });
}
```
:::

with the new ArcGIS layer:

::: code-group
<<< @/../website/js/tiles.js#arcgis-layer [website/js/tiles.js#arcgis-layer]
:::

The libraries came from two CDNs before; now everything is imported from
the vendored bundle:

::: code-group
```html [website/index.html @ bd8e191, lines 9–11]
    <link rel="stylesheet" href="css/style.css" />
    <script src="https://unpkg.com/deck.gl@9.4.0/dist.min.js"></script>
    <script type="module" src="js/main.js"></script>
```
:::

::: code-group
<<< @/../website/index.html#head-scripts [website/index.html#head-scripts]
:::
