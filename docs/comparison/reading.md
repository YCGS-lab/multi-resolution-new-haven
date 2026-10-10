# Reading COGs

## Before: CogSource with geotiff.js

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 33–80]
class CogSource {
  constructor(spec) {
    this.spec = spec;
    const nd = spec.nodata;
    // Float COGs store no data as -9999 (LERC is lossy, so compare loosely).
    this.isNodata = nd == null ? () => false : nd <= -9000 ? (v) => v < nd + 1 : (v) => v === nd;
  }

  open() {
    this.levels ??= (async () => {
      const tiff = await GeoTIFF.fromUrl(this.spec.url, { cacheSize: 2000 });
      const n = await tiff.getImageCount();
      const levels = [];
      for (let i = 0; i < n; i++) {
        const im = await tiff.getImage(i);
        const w = im.getWidth();
        levels.push({ im, w, h: im.getHeight(), res: (this.spec.res * this.spec.width) / w });
      }
      return levels.sort((a, b) => a.res - b.res);
    })();
    this.levels.catch(() => (this.levels = null));
    return this.levels;
  }

  async read(box, res, bands, { pad = 1, signal } = {}) {
    const levels = await this.open();
    // Coarsest level still at least as fine as the tile.
    let lv = levels[0];
    for (const l of levels) if (l.res <= res * 1.0001) lv = l;
    const [bx0, , , by1] = this.spec.bounds;
    const r = lv.res;
    const c0 = Math.max(0, Math.floor((box[0] - bx0) / r) - pad);
    const c1 = Math.min(lv.w, Math.ceil((box[2] - bx0) / r) + pad);
    const r0 = Math.max(0, Math.floor((by1 - box[3]) / r) - pad);
    const r1 = Math.min(lv.h, Math.ceil((by1 - box[1]) / r) + pad);
    if (c1 <= c0 || r1 <= r0) return null;
    const samples = bands.map((b) => this.spec.bands.indexOf(b));
    const rasters = await lv.im.readRasters({ window: [c0, r0, c1, r1], samples, interleave: false, signal });
    const data = {};
    bands.forEach((b, i) => {
      const src = rasters[i];
      const out = new Float32Array(src.length);
      for (let k = 0; k < src.length; k++) out[k] = this.isNodata(src[k]) ? NaN : src[k];
      data[b] = out;
    });
    return { data, width: c1 - c0, height: r1 - r0, x0: bx0 + c0 * r, y1: by1 - r0 * r, res: r };
  }
}
```
:::

`CogSource` opened the COG with geotiff.js (`fromUrl` with a 2000-block
cache), sorted its images by resolution, and for each 512-pixel deck.gl tile:

1. picked the coarsest image at least as fine as the tile;
2. computed the pixel window covering the tile's box, plus a 1-pixel pad for
   hillshades;
3. read the window with `readRasters` (only the bands the spec needs),
   decoding on the **main thread**;
4. converted no data to NaN into new `Float32Array`s.

The source was cached per catalog source, so its block cache was shared by
every product on the same COG. Switching between the five Landsat products
therefore read no new bytes.

## After: COGLayer with a custom tile loader

deck.gl-raster's `COGLayer` owns the reading. `cog.js` opens each file once
and supplies the tile loader:

::: code-group
<<< @/../website/js/cog.js#open-cogs [website/js/cog.js#open-cogs]
<<< @/../website/js/cog.js#load-tile [website/js/cog.js#load-tile]
:::

| | Before | After |
|---|---|---|
| Unit of reading | a window matching the deck.gl tile (any size) | one internal COG tile (512 × 512) |
| Requests | geotiff.js fetches blocks of the file and caches them | one range request per COG tile, limited to 6 (24 over HTTP/2) per origin |
| Decoding | main thread | worker pool |
| Result | `Float32Array` per band, NaN = no data | one GPU texture, sentinel = no data |
| Sharing | block cache per source (all products on a file) | header shared; tiles cached per layer |

::: warning Consequences, measured
- **More, smaller requests.** Loading the 4.8 m JPEG fixture made 46
  requests instead of 2, for the same bytes. Over 40 ms of latency per
  request, zooming into the 0.5 m impervious-surface COG took 1.76× longer.
- **Switching products re-downloads tiles.** 8.2 MB for five Landsat products
  on one file. The old block cache served them from memory.
- **Much less main-thread work** when switching: 210 ms of blocking instead
  of 975 ms.

See [Performance](./performance).
:::

## Choosing the overview

Before, the rule was explicit: the coarsest overview whose pixel is no
larger than a pixel of the 512-px deck.gl tile. deck.gl's tile zoom made
tile pixels 0.7–1.4 screen pixels, so the old reader often read a finer
overview than the screen needed.

After, deck.gl-raster's traversal decides per tile. A bug in v0.8.1 sizes
screen pixels for a 256-px world and so picks overviews up to twice as
coarse. `FinerCOGLayer` corrects it:

::: code-group
<<< @/../website/js/cog.js#finer-cog-layer [website/js/cog.js#finer-cog-layer]
:::

On the impervious-surface COG at the full extent, both versions now read
the 10.65 m overview. Before the fix, the new version read 21.3 m, and thin
roads vanished from the image.

## Resampling vs. meshes

Before, colors computed on the COG's own grid were **resampled onto the
deck.gl tile's 512 × 512 pixels** with nearest neighbor:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 431–449]
/** Nearest-neighbor resampling of window colors onto a w x h grid over box. */
function resample(rgba, win, box, w, h) {
  const res = (box[2] - box[0]) / w;
  const cols = new Int32Array(w);
  for (let j = 0; j < w; j++) cols[j] = Math.floor((box[0] + (j + 0.5) * res - win.x0) / win.res);
  const out = new Uint8ClampedArray(w * h * 4);
  const src = new Uint32Array(rgba.buffer, rgba.byteOffset, rgba.length / 4);
  const dst = new Uint32Array(out.buffer);
  for (let i = 0; i < h; i++) {
    const si = Math.floor((win.y1 - (box[3] - (i + 0.5) * res)) / win.res);
    if (si < 0 || si >= win.height) continue;
    const row = si * win.width;
    for (let j = 0; j < w; j++) {
      const sj = cols[j];
      if (sj >= 0 && sj < win.width) dst[i * w + j] = src[row + sj];
    }
  }
  return out;
}
```
:::

The tile was then drawn as a bitmap. Zoomed in past the finest tile zoom,
those 512 pixels were stretched. A native pixel edge could therefore only
fall on a tile-pixel edge, off by up to ~17 screen pixels at deep zoom.

After, deck.gl-raster draws each COG tile as a mesh placed by the file's
geotransform, and the texture is sampled per screen pixel. Pixel edges land
exactly where the geotransform puts them. This was measured at deep zoom:
edges at 69, 138, 207 px against expected 68.7, 137.6, 206.5.

## Upstream issue: multi-band LERC

geotiff.js handled multi-band LERC tiles correctly. deck.gl-raster 0.8.1
does not: it returns all bands in one array and mislabels the layout. The
new loader has to unpack them:

::: code-group
<<< @/../website/js/cog.js#band-arrays [website/js/cog.js#band-arrays]
:::
