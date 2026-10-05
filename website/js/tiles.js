// Dynamic, tiled rendering of catalog products.
//
// Each product is one deck.gl TileLayer. For every tile, each of the
// product's layers reads its source for the tile's area at about the tile's
// resolution -- a window of a local COG (at the matching overview), an ArcGIS
// ImageServer exportImage request, or a mosaic of XYZ tiles -- colors the
// values on the source's own pixel grid with the layer's render spec (band
// combination, value range, colormap, hillshade; see scripts/common/web.py),
// and resamples the colors onto the tile with nearest neighbor, so native
// pixels stay sharp blocks. Layers are then composited bottom to top.
//
// Coordinates: sources and requests use absolute EPSG:3857 meters; deck.gl
// world coordinates are EPSG:3857 relative to catalog.origin (see catalog.js).

import * as GeoTIFF from "https://cdn.jsdelivr.net/npm/geotiff@2.1.3/+esm";

const { TileLayer, BitmapLayer } = deck;

const R = 6378137;
const CIRCUMFERENCE = 2 * Math.PI * R;
// Each tile is TILE_SIZE x TILE_SIZE pixels; on high-DPI screens tiles are one
// zoom level finer, so a tile pixel is about one device pixel.
const TILE_SIZE = 512;
const ZOOM_OFFSET = window.devicePixelRatio > 1.5 ? 1 : 0;

// --------------------------------------------------------------------------
// Sources: read(box, res, bands, {pad, signal}) -> window on the source grid
//   box: [xmin, ymin, xmax, ymax] (EPSG:3857), res: wanted EPSG:3857 m / pixel
//   window: {data: {band: Float32Array (NaN = no data)} | rgba: Uint8ClampedArray,
//            width, height, x0, y1, res}   (x0, y1: upper-left corner)
// --------------------------------------------------------------------------

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

class ArcgisSource {
  constructor(spec) {
    this.spec = spec;
  }

  /** Like _read, retried once: the services occasionally send a truncated image. */
  async read(box, res, bands, opts = {}) {
    try {
      return await this._read(box, res, opts);
    } catch (err) {
      if (opts.signal?.aborted) throw err;
      return this._read(box, res, opts);
    }
  }

  async _read(box, res, { pad = 0, signal } = {}) {
    const s = this.spec;
    const b = [box[0] - pad * res, box[1] - pad * res, box[2] + pad * res, box[3] + pad * res];
    const w = Math.round((b[2] - b[0]) / res);
    const h = Math.round((b[3] - b[1]) / res);
    const p = new URLSearchParams({
      bbox: b.map((v) => v.toFixed(3)).join(","),
      bboxSR: 3857,
      imageSR: 3857,
      size: `${w},${h}`,
      f: "image",
    });
    if (s.band_ids) p.set("bandIds", s.band_ids.join(","));
    if (s.raw) {
      p.set("format", "tiff");
      p.set("pixelType", "F32");
      p.set("renderingRule", JSON.stringify({ rasterFunction: "None" }));
      if (s.nodata != null) p.set("noData", s.nodata);
      p.set("interpolation", "RSP_BilinearInterpolation");
    } else {
      p.set("format", "jpgpng");
      // True pixels near native resolution; smooth when zoomed out.
      p.set("interpolation", res < s.res * 1.5 ? "RSP_NearestNeighbor" : "RSP_BilinearInterpolation");
    }
    const resp = await fetch(`${s.url}/exportImage?${p}`, { signal });
    if (!resp.ok) throw new Error(`${s.url}: HTTP ${resp.status}`);
    const type = resp.headers.get("content-type") || "";
    if (type.startsWith("application/json") || type.startsWith("text/")) throw new Error(`${s.url}: ${(await resp.text()).slice(0, 200)}`);
    const win = { width: w, height: h, x0: b[0], y1: b[3], res };
    if (!s.raw) return { ...win, rgba: await decodeImage(await resp.blob(), w, h) };
    let band;
    try {
      const buf = await resp.arrayBuffer();
      const im = await (await GeoTIFF.fromArrayBuffer(buf)).getImage();
      band = im.fileDirectory.TileByteCounts?.includes(0)
        ? readSparseTiles(im, buf)
        : (await im.readRasters({ interleave: false, signal }))[0];
    } catch (err) {
      throw new Error(`${resp.url}: ${err.message}`);
    }
    const nd = s.nodata ?? -Infinity;
    const out = new Float32Array(band.length);
    for (let k = 0; k < band.length; k++) {
      const v = band[k];
      out[k] = Number.isFinite(v) && v > nd && v > -1e30 ? v * s.scale : NaN;
    }
    return { ...win, data: { [s.bands[0]]: out } };
  }
}

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

async function decodeImage(blob, w, h) {
  const img = await createImageBitmap(blob);
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  ctx.drawImage(img, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h).data;
}

const sources = new Map();

function getSource(catalog, id) {
  if (!sources.has(id)) {
    const spec = catalog.sources[id];
    if (!spec) throw new Error(`unknown source ${id}`);
    const Cls = { cog: CogSource, arcgis: ArcgisSource, xyz: XyzSource }[spec.type];
    if (!Cls) throw new Error(`${id}: unsupported source type ${spec.type}`);
    sources.set(id, new Cls(spec));
  }
  return sources.get(id);
}

// --------------------------------------------------------------------------
// Render specs: window values -> RGBA on the source grid
// --------------------------------------------------------------------------

const exprCache = new Map();

/** A per-pixel function of named bands, e.g. "hh - hv" (Math functions allowed). */
function compileExpr(expr, bands) {
  const key = `${expr}|${bands}`;
  if (!exprCache.has(key)) {
    exprCache.set(key, new Function(...bands, `const {log10, log, exp, sqrt, abs, min, max, pow} = Math; return (${expr});`));
  }
  return exprCache.get(key);
}

const identifiers = (expr) => expr.match(/[A-Za-z_]\w*/g) ?? [];

/** Band names a render spec reads. */
function renderBands(r, sourceBands) {
  const names = new Set();
  const add = (v) => {
    if (v.band) names.add(v.band);
    if (v.expr) identifiers(v.expr).forEach((n) => sourceBands.includes(n) && names.add(n));
  };
  if (r.type === "identity")
    sourceBands.slice(0, 3).forEach((b) => names.add(b)); // RGB as stored
  else if (r.type === "rgb") r.channels.forEach(add);
  else if (r.type === "colormap" || r.type === "categorical") add(r);
  if (r.shade) names.add(r.shade.band);
  return [...names];
}

/** Values of a band or expression over the window. */
function values(v, win) {
  if (v.band) return win.data[v.band];
  const names = Object.keys(win.data);
  const f = compileExpr(v.expr, names);
  const arrays = names.map((n) => win.data[n]);
  const n = win.width * win.height;
  const out = new Float32Array(n);
  const args = new Array(names.length);
  for (let k = 0; k < n; k++) {
    for (let i = 0; i < arrays.length; i++) args[i] = arrays[i][k];
    out[k] = f(...args);
  }
  return out;
}

const lat = (y) => (2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * (180 / Math.PI);

/** Hillshade (0-1) as in render.hillshade: azimuth 315, altitude 45, np.gradient differences. */
function hillshade(z, win) {
  const { width: w, height: h } = win;
  const yc = win.y1 - (win.height * win.res) / 2;
  const d = win.res * Math.cos((lat(yc) * Math.PI) / 180); // ground meters per pixel
  const az = ((360 - 315 + 90) * Math.PI) / 180;
  const alt = (45 * Math.PI) / 180;
  const out = new Float32Array(w * h);
  for (let i = 0; i < h; i++) {
    const iu = i > 0 ? i - 1 : i;
    const id = i < h - 1 ? i + 1 : i;
    for (let j = 0; j < w; j++) {
      const jl = j > 0 ? j - 1 : j;
      const jr = j < w - 1 ? j + 1 : j;
      const gx = (z[i * w + jr] - z[i * w + jl]) / ((jr - jl) * d);
      const gy = (z[id * w + j] - z[iu * w + j]) / ((id - iu) * d);
      const slope = Math.atan(Math.hypot(gx, gy));
      const aspect = Math.atan2(-gx, gy);
      const hs = Math.sin(alt) * Math.cos(slope) + Math.cos(alt) * Math.sin(slope) * Math.cos(az - aspect);
      out[i * w + j] = hs < 0 ? 0 : hs > 1 ? 1 : hs;
    }
  }
  return out;
}

const rgbCache = new Map();
function hexRgb(hex) {
  if (!rgbCache.has(hex)) {
    const h = hex.replace("#", "");
    const n = (i) => parseInt(h.slice(i, i + 2), 16);
    rgbCache.set(hex, [n(0), n(2), n(4), h.length >= 8 ? n(6) : 255]);
  }
  return rgbCache.get(hex);
}

/** Linear (or log) normalization with gamma: value -> 0..1 (may be outside). */
function normalizer(r) {
  const g = 1 / (r.gamma ?? 1);
  const pow = (t) => (g === 1 || t <= 0 || t >= 1 ? t : t ** g);
  if (r.scale === "log") {
    const l0 = Math.log(r.vmin);
    const span = Math.log(r.vmax) - l0;
    return (v) => (v <= 0 ? -1 : pow((Math.log(v) - l0) / span));
  }
  const lo = r.vmin ?? r.min;
  const span = (r.vmax ?? r.max) - lo;
  return (v) => pow((v - lo) / span);
}

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

function colorize(r, win) {
  const n = win.width * win.height;
  if (r.type === "identity") {
    const rgba = win.rgba ? new Uint8ClampedArray(win.rgba) : bandsToRgba(win);
    const { desaturate: ds = 0, lighten: lt = 0 } = r;
    if (ds || lt)
      for (let k = 0; k < n * 4; k += 4) {
        const gray = 0.299 * rgba[k] + 0.587 * rgba[k + 1] + 0.114 * rgba[k + 2];
        for (let c = 0; c < 3; c++) {
          const v = (1 - ds) * rgba[k + c] + ds * gray;
          rgba[k + c] = 255 - (1 - lt) * (255 - v);
        }
      }
    return rgba;
  }
  const out = new Uint8ClampedArray(n * 4);
  if (r.type === "rgb") {
    const chans = r.channels.map((c) => ({ v: values(c, win), f: normalizer(c) }));
    for (let k = 0; k < n; k++) {
      let ok = true;
      for (let c = 0; c < 3; c++) {
        const v = chans[c].v[k];
        if (Number.isNaN(v)) ok = false;
        const t = chans[c].f(v);
        out[k * 4 + c] = 255 * (t < 0 ? 0 : t > 1 ? 1 : t) + 0.5;
      }
      out[k * 4 + 3] = ok ? 255 : 0;
    }
    return out;
  }
  if (r.type === "categorical") {
    const v = values(r, win);
    const lut = Object.fromEntries(Object.entries(r.colors).map(([k, c]) => [k, hexRgb(c)]));
    for (let k = 0; k < n; k++) {
      const c = lut[v[k]];
      if (c) out.set(c, k * 4);
    }
    return out;
  }
  if (r.type === "colormap") {
    let v = values(r, win);
    if (r.hillshade) {
      const hs = hillshade(v, win);
      for (let k = 0; k < n; k++) if (Number.isNaN(v[k])) hs[k] = NaN;
      v = hs;
    }
    const f = normalizer(r);
    const colors = r.colors.map(hexRgb);
    const under = hexRgb(r.under);
    const over = hexRgb(r.over);
    const N = colors.length;
    for (let k = 0; k < n; k++) {
      if (Number.isNaN(v[k])) continue;
      const t = f(v[k]);
      out.set(t < 0 ? under : t > 1 ? over : colors[Math.min(N - 1, Math.floor(t * N))], k * 4);
    }
    if (r.shade) {
      const z = win.data[r.shade.band];
      const hs = r.shade.precomputed ? z : hillshade(z, win);
      const s = r.shade.strength;
      for (let k = 0; k < n; k++) {
        const m = 1 - s + s * (Number.isNaN(hs[k]) ? 1 : hs[k]);
        out[k * 4] *= m;
        out[k * 4 + 1] *= m;
        out[k * 4 + 2] *= m;
      }
    }
    return out;
  }
  throw new Error(`unsupported render type ${r.type}`);
}

// --------------------------------------------------------------------------
// Tiles
// --------------------------------------------------------------------------

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

/** Deepest tile zoom worth requesting: tile pixels as fine as the finest source pixels. */
function maxTileZoom(catalog, product) {
  const res = Math.min(...product.layers.map((l) => catalog.sources[l.source].res));
  return Math.ceil(Math.log2(1 / res) - 1e-6);
}

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
