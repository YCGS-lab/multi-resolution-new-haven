# Views and compositing

## OrthographicView to MapView

Before, each map was a deck.gl `OrthographicView` that drew in world
coordinates directly: one unit per Web Mercator meter from the extent
center, with zoom as log2 of pixels per meter. The app's view state *was*
deck.gl's view state:

::: code-group
```js [website/js/viewer.js @ bd8e191, lines 73–90]
    this.size = [this.mapEl.clientWidth || 800, this.mapEl.clientHeight || 450];
    this.viewState = homeViewState(catalog.extent, ...this.size);
    this.deck = new Deck({
      parent: this.mapEl,
      views: new OrthographicView({ id: "main", flipY: false, controller: { inertia: 250 } }),
      viewState: this.viewState,
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(viewState, catalog.extent, ...this.size);
        this.update();
        return this.viewState;
      },
      onResize: ({ width, height }) => {
        this.size = [width, height];
        this.viewState = clampViewState(this.viewState, catalog.extent, width, height);
        this.update();
      },
      layers: [],
    });
```
:::

deck.gl-raster draws COG tiles in deck.gl's Web Mercator common space and
picks tiles for a `WebMercatorViewport`, so it needs a `MapView`. The app
keeps its world view state and converts at the boundary:

::: code-group
<<< @/../website/js/mapview.js#deck-view-state [website/js/mapview.js#deck-view-state]
<<< @/../website/js/viewer.js#viewer-deck [website/js/viewer.js#viewer-deck]
:::

The grid's per-slot views changed the same way:

::: code-group
```js [website/js/grid.js @ bd8e191, lines 301–311]
      views.push(
        new OrthographicView({
          id: s.uid,
          x: b.left - canvas.left,
          y: b.top - canvas.top,
          width: w,
          height: h,
          flipY: false,
          controller: this.rearrange ? false : { inertia: 250 },
        }),
      );
```
:::

::: code-group
<<< @/../website/js/grid.js#grid-render [website/js/grid.js#grid-render]
:::

Unchanged by this: zoom limits, axes, scale bar, swipe and spy positions,
and the URL. They all still work in world coordinates. See
[Map views](/website/map-views).

## Compositing

Before, a product was **one** deck.gl layer. Its tiles composited all the
product's layers (e.g. ICESat-2: basemap + ground points + canopy points)
into one bitmap on the CPU:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 490–528]
/** Alpha-composite `top` over `out` (straight alpha). */
function over(out, top) {
  for (let k = 0; k < out.length; k += 4) {
    const a = top[k + 3] / 255;
    if (!a) continue;
    if (a === 1 || !out[k + 3]) {
      out.set(top.subarray(k, k + 4), k);
      continue;
    }
    const b = (out[k + 3] / 255) * (1 - a);
    const ao = a + b;
    for (let c = 0; c < 3; c++) out[k + c] = (top[k + c] * a + out[k + c] * b) / ao;
    out[k + 3] = ao * 255;
  }
}

/** RGBA image (ImageData, or null if empty) of a product over box (EPSG:3857), w x h pixels. */
export async function renderTile(catalog, product, box, w, h, signal) {
  const res = (box[2] - box[0]) / w;
  let out = null;
  for (const layer of product.layers) {
    const src = getSource(catalog, layer.source);
    const r = layer.render;
    const m = layer.dilate_px || 0;
    const W = w + 2 * m;
    const H = h + 2 * m;
    const b = [box[0] - m * res, box[1] - m * res, box[2] + m * res, box[3] + m * res];
    const needsNeighbors = r.hillshade || (r.shade && !r.shade.precomputed);
    const win = await src.read(b, res, renderBands(r, src.spec.bands), { pad: needsNeighbors ? 1 : 0, signal });
    if (!win) continue;
    let rgba = (src.spec.smooth ? resampleSmooth : resample)(colorize(r, win), win, b, W, H);
    if (m) rgba = crop(dilate(rgba, W, H, m), W, m, w, h);
    if (out) over(out, rgba);
    else out = rgba;
  }
  if (!out) return null;
  for (let k = 3; k < out.length; k += 4) if (out[k]) return new ImageData(out, w, h);
  return null;
}
```
:::

After, each product layer is its own deck.gl layer, and the GPU blends them:

::: code-group
<<< @/../website/js/tiles.js#product-layers [website/js/tiles.js#product-layers]
:::

The visible effect: in **opacity** compare mode, a multi-layer product B is
faded layer by layer, so B's basemap and B's points are each 50%
transparent over A. The old version faded one composited image. Single-layer
products (almost all) look the same.

## Compare modes

The old swipe used one clip box in world meters for every layer:

::: code-group
```js [website/js/viewer.js @ bd8e191, lines 157–196]
  layers() {
    const c = this.catalog;
    const [w, h] = this.size;
    const layers = [backgroundLayer("bg", c.extent)];
    const a = c.get(this.sel.a);
    if (a) layers.push(...productLayers("a", c, a, this.loading));
    const b = this.compare && c.get(this.sel.b);
    if (b) {
      let props = null;
      let lens = null;
      if (this.mode === "swipe") {
        const x = unproject(this.viewState, w, h, this.swipe * w, 0)[0];
        props = { extensions: [clipExtension], clipBounds: [x, -1e8, 1e8, 1e8] };
      } else if (this.mode === "opacity") {
        props = { opacity: this.opacity };
      } else if (this.spy) {
        const [cx, cy] = unproject(this.viewState, w, h, ...this.spy);
        const r = SPY_RADIUS / 2 ** this.viewState.zoom;
        const ring = Array.from({ length: 97 }, (_, i) => [cx + r * Math.cos((i * Math.PI) / 48), cy + r * Math.sin((i * Math.PI) / 48)]);
        layers.push(new SolidPolygonLayer({ id: "spy-mask", operation: "mask", data: [{ polygon: ring }], getPolygon: (d) => d.polygon }));
        lens = new PathLayer({
          id: "spy-ring",
          data: [{ path: ring }],
          getPath: (d) => d.path,
          getColor: [255, 255, 255, 230],
          getWidth: 2,
          widthUnits: "pixels",
        });
        props = { extensions: [maskExtension], maskId: "spy-mask" };
      }
      if (props) {
        // B's own no-data background, so A does not show through B's transparent pixels.
        if (this.mode !== "opacity") layers.push(backgroundLayer("bg-b", c.extent).clone(props));
        layers.push(...productLayers("b", c, b, this.loading, props));
        if (lens) layers.push(lens);
      }
    }
    if (this.settings.labels) layers.push(...landmarkLayers("landmarks", c, a?.landmark_color));
    return layers;
  }
```
:::

Now the clip bounds must be in each layer's own coordinates:
longitude/latitude for most layers, deck.gl common space for COG meshes.
COG meshes also need `clipByInstance: false`:

::: code-group
<<< @/../website/js/mapview.js#overlay-props [website/js/mapview.js#overlay-props]
<<< @/../website/js/viewer.js#compare-layers [website/js/viewer.js#compare-layers]
:::

The background and landmarks moved from world coordinates to
longitude/latitude, since `MapView` positions are geographic:

::: code-group
```js [website/js/mapview.js @ bd8e191, lines 57–65]
/** Gray "no data" background over the whole extent. */
export function backgroundLayer(id, extent) {
  return new SolidPolygonLayer({ id, data: [{ polygon: rect(extent) }], getPolygon: (d) => d.polygon, getFillColor: NODATA_FILL });
}

/** The product's tiled layer (see tiles.js); `props` go to its tiles, e.g. clipping. */
export function productLayers(id, catalog, product, loading, props = {}) {
  return [productLayer(id, catalog, product, { loading, props })];
}
```
:::
