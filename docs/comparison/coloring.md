# Coloring

The render specs did not change. How they are applied did.

## Before: JavaScript, per tile

Every tile of every COG layer went through `colorize`: a loop over the
pixels of the window, building an RGBA array. That function still exists,
unchanged, for ArcGIS tiles:

::: code-group
<<< @/../website/js/tiles.js#cpu-colorize [website/js/tiles.js#cpu-colorize]
:::

Identity products on COGs (JPEG imagery) went through a helper that is now
gone:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 341–353]
/** RGBA from the first three bands of a window (0-255 values, e.g. a JPEG COG). */
function bandsToRgba(win) {
  const [r, g, b] = Object.values(win.data);
  const out = new Uint8ClampedArray(r.length * 4);
  for (let k = 0; k < r.length; k++) {
    if (Number.isNaN(r[k]) || Number.isNaN(g[k]) || Number.isNaN(b[k])) continue;
    out[k * 4] = r[k];
    out[k * 4 + 1] = g[k];
    out[k * 4 + 2] = b[k];
    out[k * 4 + 3] = 255;
  }
  return out;
}
```
:::

Then the colors were resampled onto the tile
([Reading COGs](./reading#resampling-vs-meshes)), dilated if the layer
asked for it, cropped, and composited:

::: code-group
```js [website/js/tiles.js @ bd8e191, lines 463–488]
/** Grow opaque pixels into transparent ones within r pixels (square neighborhood). */
function dilate(rgba, w, h, r) {
  const pass = (src, horizontal) => {
    const s = new Uint32Array(src.buffer);
    const out = new Uint32Array(s);
    for (let i = 0; i < h; i++)
      for (let j = 0; j < w; j++) {
        const k = i * w + j;
        if (s[k] >>> 24) continue;
        for (let d = 1; d <= r; d++) {
          const a = horizontal ? (j - d >= 0 ? k - d : -1) : i - d >= 0 ? k - d * w : -1;
          const b = horizontal ? (j + d < w ? k + d : -1) : i + d < h ? k + d * w : -1;
          if (a >= 0 && s[a] >>> 24) { out[k] = s[a]; break; } // prettier-ignore
          if (b >= 0 && s[b] >>> 24) { out[k] = s[b]; break; } // prettier-ignore
        }
      }
    return new Uint8ClampedArray(out.buffer);
  };
  return pass(pass(rgba, true), false);
}

function crop(rgba, w, m, cw, ch) {
  const out = new Uint8ClampedArray(cw * ch * 4);
  for (let i = 0; i < ch; i++) out.set(rgba.subarray(((i + m) * w + m) * 4, ((i + m) * w + m + cw) * 4), i * cw * 4);
  return out;
}
```
:::

## After: GLSL, per screen pixel

`compile` writes a shader module per render spec. The same four render
types, side by side with the CPU version:

| Render type | CPU (`colorize`, still used for ArcGIS) | GPU (generated module) |
|---|---|---|
| identity | copy RGBA; desaturate/lighten per pixel | `vec4 c = v`; same formula in GLSL |
| rgb | `values()` per channel (expressions via `new Function`), `normalizer`, clamp, scale to 0–255 | expressions translated to GLSL; same normalization inlined |
| colormap | `normalizer`, `colors[floor(t·N)]`, under/over; hillshade by `hillshade()` on the window | same; colors from a 256 × 1 texture; only stored hillshades |
| categorical | `lut[value]` | 256 × 1 texture indexed by the code |

::: code-group
<<< @/../website/js/cog.js#compile-colormap [website/js/cog.js#compile-colormap]
<<< @/../website/js/cog.js#normalize-glsl [website/js/cog.js#normalize-glsl]
<<< @/../website/js/cog.js#glsl-expr [website/js/cog.js#glsl-expr]
:::

### Matching the old output

The GLSL is written to give the same colors as the JavaScript:

- the same normalization (gamma applied only strictly between 0 and 1, log
  scale with values ≤ 0 counted as "under");
- the same color index `floor(t × 256)`, sampled at the texel center with no
  interpolation;
- the same no-data rule (any band of the value missing → transparent);
- the same dilation order (same row first, then nearest rows);
- the same shading formula `1 − s + s · hs`.

Screenshots of every product were compared with the old site. Apart from
the dilation width, the differences are sampling phase on high-frequency
data and a slightly different overview choice.

### Why not deck.gl-raster's modules

deck.gl-raster ships shader modules for common cases. None fits the render
specs, so `cog.js` generates its own:

| Module | What it does | Why not used |
|---|---|---|
| `CreateTexture` | samples the tile texture into `color` | `dilate_px` must sample neighbors, so the generated module samples its own texture |
| `LinearRescale` | one min/max for all channels | specs have per-channel ranges and gamma, log scales and expressions |
| `Colormap` | looks up `color.r` in a named-colormap sprite | overwrites the whole color: no under/over colors, no transparent no data. Colormaps here are arbitrary 256-color lists from matplotlib |
| `FilterNoDataVal` | discards one exact value | LERC is lossy, so no data is "below −9000"; expressions need every band they read |
| `CompositeBands` | up to 4 band textures into RGBA | all needed bands already go into one texture |

### What stayed

- **ArcGIS tiles** are still colored by `colorize` on the CPU, including
  hillshades computed in the browser for the lidar and 3DEP DEMs. The
  render specs therefore have two implementations, which must be kept in
  step. See [Image-service layers](/website/image-services#cpu-coloring).
- **Hillshades computed from a COG's elevation band** are no longer
  supported. No COG used them; `compile` throws an error if a spec asks.

### Behavior differences

- `dilate_px` is now in device pixels, so points look somewhat larger. It
  stops at COG tile edges, where the CPU version read across them. It no
  longer drops points between tiles, which the old tile resampling
  sometimes did.
- In opacity compare mode, multi-layer products fade layer by layer
  ([Views and compositing](./views#compositing)).
- The basemap is desaturated with deck.gl's luminance weights, not the old
  0.299/0.587/0.114.
