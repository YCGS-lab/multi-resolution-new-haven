// Tiled rendering of catalog products: one deck.gl layer per product layer.
//
// Layers on a local COG are deck.gl-raster COGLayers (cog.js). Layers on an
// image service are deck.gl TileLayers over Web Mercator tiles:
//
//   - ArcGIS ImageServer: for every tile, an exportImage request for the
//     tile's area at the tile's resolution, colored on the CPU with the
//     layer's render spec (band combination, value range, colormap,
//     hillshade; see scripts/common/web.py). The service can depend on the
//     selected timestep (`variants`, e.g. one service per survey year).
//   - XYZ map tiles: the tiles themselves, scaled smoothly, optionally
//     desaturated and lightened (as a basemap); the URL may hold the
//     timestep's parameters and the user's credentials.
//   - Planetary Computer mosaics ("pc-mosaic"): a mosaic search registered
//     for the selected timestep or window and filters, whose tiles are raw
//     values (NPY), colored on the CPU like ArcGIS tiles, or 8-bit images.
//   - titiler-cmr ("titiler-cmr"): raw values (NPY) of NASA granules
//     mosaicked over the selected timestep or window.
//
// Layers on the Climate Data Store ("cds") are one image per hour over the
// area in view (cds.js).
//
// Rendered tiles of the live sources go through one cache (tileCache), which
// the animation tab fills ahead of time (prefetchTiles).
//
// Coordinates: sources and requests use absolute EPSG:3857 meters; deck.gl
// layers use longitude / latitude (MapView).

import { BitmapLayer, GeoTIFF, SolidPolygonLayer, TileLayer } from "../vendor/deck-gl-raster.js";
import { cachedGrid, cdsArea, cdsGrids, hourKey } from "./cds.js";
import { cogLayer } from "./cog.js";
import { credential, env } from "./env.js";

const R = 6378137;
const CIRCUMFERENCE = 2 * Math.PI * R;
// Each tile is TILE_SIZE x TILE_SIZE pixels; on high-DPI screens tiles are one
// zoom level finer, so a tile pixel is about one device pixel.
const TILE_SIZE = 512;
const ZOOM_OFFSET = window.devicePixelRatio > 1.5 ? 1 : 0;

const mercX = (lon) => (R * lon * Math.PI) / 180;
const mercY = (lat) => R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

// --------------------------------------------------------------------------
// ArcGIS ImageServer: read(box, res) -> window on the requested grid
//   box: [xmin, ymin, xmax, ymax] (EPSG:3857), res: EPSG:3857 m / pixel
//   window: {data: {band: Float32Array (NaN = no data)} | rgba: Uint8ClampedArray,
//            width, height, x0, y1, res}   (x0, y1: upper-left corner)
// --------------------------------------------------------------------------

class ArcgisSource {
  constructor(spec) {
    this.spec = spec;
  }

  /** Like _read, retried once: the services occasionally send a truncated image. */
  async read(box, res, opts = {}) {
    try {
      return await this._read(box, res, opts);
    } catch (err) {
      if (opts.signal?.aborted) throw err;
      return this._read(box, res, opts);
    }
  }

  // #region arcgis-request
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
      band = await readFloatTiff(await resp.arrayBuffer(), signal);
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
  // #endregion arcgis-request
}

// #region read-float-tiff
/**
 * Band 1 of a tiled float32 TIFF (as exportImage writes), NaN where tiles are
 * sparse (ArcGIS leaves out tiles without data).
 */
async function readFloatTiff(buf, signal) {
  const tiff = await GeoTIFF.fromArrayBuffer(buf);
  const { width: W, height: H, tileWidth: tw, tileHeight: th } = tiff;
  const out = new Float32Array(W * H).fill(NaN);
  const jobs = [];
  for (let ty = 0; ty * th < H; ty++)
    for (let tx = 0; tx * tw < W; tx++)
      jobs.push(
        tiff.fetchTile(tx, ty, { boundless: false, signal }).then(
          ({ array }) => {
            const data = array.layout === "band-separate" ? array.bands[0] : array.data;
            const step = array.layout === "band-separate" ? 1 : array.count;
            for (let r = 0; r < array.height; r++)
              for (let c = 0; c < array.width; c++) out[(ty * th + r) * W + tx * tw + c] = data[(r * array.width + c) * step];
          },
          (err) => {
            if (!/not found/.test(err.message)) throw err; // sparse tile: no data
          },
        ),
      );
  await Promise.all(jobs);
  return out;
}
// #endregion read-float-tiff

async function decodeImage(blob, w, h) {
  const img = await createImageBitmap(blob);
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  ctx.drawImage(img, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h).data;
}

const arcgisSources = new Map();

/** The source spec for a timestep: the spec with that timestep's variant (if any) applied. */
export function sourceSpec(catalog, id, t) {
  const spec = catalog.sources[id];
  const v = t != null && spec.variants?.[t];
  return v ? { ...spec, ...v } : spec;
}

function arcgisSource(catalog, id, t) {
  const spec = sourceSpec(catalog, id, t);
  const key = `${spec.url}|${spec.band_ids}`;
  if (!arcgisSources.has(key)) arcgisSources.set(key, new ArcgisSource(spec));
  return arcgisSources.get(key);
}

// --------------------------------------------------------------------------
// Render specs: window values -> RGBA on the source grid (ArcGIS only; COG
// layers do the same on the GPU, see cog.js)
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

// #region cpu-hillshade
/** Hillshade (0-1) as in render.hillshade: azimuth 315, altitude 45, np.gradient differences. */
function hillshade(z, win) {
  const { width: w, height: h } = win;
  const yc = win.y1 - (win.height * win.res) / 2;
  const d = win.res * Math.cos((lat(yc) * Math.PI) / 180); // ground meters per pixel
  // Check the angle convention: compass (0 = north, clockwise) vs. math
  // (0 = east, counterclockwise). Both angles here are compass; mixing the two
  // mirrors the light across the NE-SW line (azimuth 315 would light from 135).
  const azCompass = (315 * Math.PI) / 180;
  const alt = (45 * Math.PI) / 180;
  const out = new Float32Array(w * h);
  for (let i = 0; i < h; i++) {
    const iu = i > 0 ? i - 1 : i;
    const id = i < h - 1 ? i + 1 : i;
    for (let j = 0; j < w; j++) {
      const jl = j > 0 ? j - 1 : j;
      const jr = j < w - 1 ? j + 1 : j;
      const gx = (z[i * w + jr] - z[i * w + jl]) / ((jr - jl) * d); // toward the east
      const gy = (z[id * w + j] - z[iu * w + j]) / ((id - iu) * d); // toward the south
      const slope = Math.atan(Math.hypot(gx, gy));
      const aspectCompass = Math.atan2(-gx, gy); // downslope direction: (east, north) = (-gx, gy)
      const hs = Math.sin(alt) * Math.cos(slope) + Math.cos(alt) * Math.sin(slope) * Math.cos(azCompass - aspectCompass);
      out[i * w + j] = hs < 0 ? 0 : hs > 1 ? 1 : hs;
    }
  }
  return out;
}
// #endregion cpu-hillshade

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

// #region cpu-colorize
function colorize(r, win) {
  const n = win.width * win.height;
  if (r.type === "identity") {
    const rgba = new Uint8ClampedArray(win.rgba);
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
// #endregion cpu-colorize

// --------------------------------------------------------------------------
// Layers
// --------------------------------------------------------------------------

/** Pixels [m, m + w) x [m, m + h) of a W-wide RGBA image. */
function crop(rgba, W, m, w, h) {
  if (!m) return rgba;
  const out = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < h; i++) out.set(rgba.subarray(((i + m) * W + m) * 4, ((i + m) * W + m + w) * 4), i * w * 4);
  return out;
}

// #region render-arcgis-tile
/** RGBA image (ImageData, or null if empty) of an ArcGIS layer over box (EPSG:3857), w x h pixels. */
export async function renderArcgisTile(catalog, layer, box, w, h, signal, t = null) {
  const src = arcgisSource(catalog, layer.source, t);
  const r = layer.render;
  const pad = r.hillshade || (r.shade && !r.shade.precomputed) ? 1 : 0;
  const win = await src.read(box, (box[2] - box[0]) / w, { pad, signal });
  const out = crop(colorize(r, win), win.width, pad, w, h);
  for (let k = 3; k < out.length; k += 4) if (out[k]) return new ImageData(out, w, h);
  return null;
}
// #endregion render-arcgis-tile

// --------------------------------------------------------------------------
// Raw tiles from tilers (NPY) and images
// --------------------------------------------------------------------------

// #region parse-npy
/** A NumPy .npy file: {shape, data: typed array (C order)}. */
export function parseNpy(buf) {
  const b = new Uint8Array(buf);
  if (b[0] !== 0x93 || String.fromCharCode(...b.subarray(1, 6)) !== "NUMPY") throw new Error("not an NPY file");
  const v1 = b[6] === 1;
  const hlen = v1 ? b[8] | (b[9] << 8) : new DataView(buf).getUint32(8, true);
  const off = (v1 ? 10 : 12) + hlen;
  const header = new TextDecoder().decode(b.subarray(v1 ? 10 : 12, off));
  const descr = /'descr':\s*'([^']+)'/.exec(header)[1];
  const shape = /'shape':\s*\(([^)]*)\)/.exec(header)[1].split(",").filter((x) => x.trim()).map(Number);
  if (/'fortran_order':\s*True/.test(header)) throw new Error("NPY: Fortran order is not supported");
  const types = { "|u1": Uint8Array, "<u1": Uint8Array, "|i1": Int8Array, "<u2": Uint16Array, "<i2": Int16Array, "<u4": Uint32Array, "<i4": Int32Array, "<f4": Float32Array, "<f8": Float64Array };
  const T = types[descr];
  if (!T) throw new Error(`NPY: unsupported dtype ${descr}`);
  const n = shape.reduce((a, c) => a * c, 1);
  const data = off % T.BYTES_PER_ELEMENT ? new T(buf.slice(off, off + n * T.BYTES_PER_ELEMENT)) : new T(buf, off, n);
  return { shape, data };
}
// #endregion parse-npy

/**
 * A window ({data: {band: Float32Array}, width, height, ...}) from an NPY tile
 * of shape (bands + mask, h, w): band i named names[i], times scale[name]
 * plus offset[name]; no data where the mask (last band) is 0 or a value is `nodata`.
 */
function npyWindow({ shape, data }, names, spec, box, extra = {}) {
  const [nb, h, w] = shape;
  const n = h * w;
  const mask = data.subarray((nb - 1) * n, nb * n);
  const out = {};
  names.forEach((name, i) => {
    const sc = spec.scale?.[name] ?? 1;
    const of = spec.offset?.[name] ?? 0;
    const nd = spec.nodata;
    const src = data.subarray(i * n, (i + 1) * n);
    const v = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      const x = src[k];
      v[k] = !mask[k] || x === nd || !Number.isFinite(x) ? NaN : x * sc + of;
    }
    out[name] = v;
  });
  for (const [name, expr] of Object.entries(extra)) {
    const f = compileExpr(expr, Object.keys(out));
    const arrays = Object.values(out);
    const v = new Float32Array(n);
    const args = new Array(arrays.length);
    for (let k = 0; k < n; k++) {
      for (let a = 0; a < arrays.length; a++) args[a] = arrays[a][k];
      const r = f(...args);
      v[k] = Number.isFinite(r) ? r : NaN;
    }
    out[name] = v;
  }
  return { data: out, width: w, height: h, x0: box[0], y1: box[3], res: (box[2] - box[0]) / w };
}

/** Bands a render spec reads (band names, and names in expressions). */
function usedBands(r, bands) {
  const names = new Set();
  const add = (v) => {
    if (v.band) names.add(v.band);
    else if (v.expr) (v.expr.match(/[A-Za-z_]\w*/g) ?? []).forEach((n) => bands.includes(n) && names.add(n));
  };
  if (r.type === "rgb") r.channels.forEach(add);
  else if (r.type === "identity") bands.slice(0, 3).forEach((b) => names.add(b));
  else add(r);
  if (r.shade) names.add(r.shade.band);
  return bands.filter((b) => names.has(b));
}

/** RGBA ImageData of a window colored with a render spec (null when empty). */
function toImage(r, win) {
  const out = colorize(r, win);
  for (let k = 3; k < out.length; k += 4) if (out[k]) return new ImageData(out, win.width, win.height);
  return null;
}

async function fetchOk(url, init, what) {
  let res = await fetch(url, init);
  if (res.status >= 500 && !init?.signal?.aborted) {
    // tilers occasionally fail under load: one retry after a pause
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 1000));
    res = await fetch(url, init);
  }
  if (res.status === 204 || res.status === 404) return null; // no data in this tile
  if (!res.ok) {
    const text = (await res.text().catch(() => "")).slice(0, 200);
    throw new Error(`${what}: HTTP ${res.status} ${text}`);
  }
  return res;
}

// --------------------------------------------------------------------------
// Planetary Computer mosaics
// --------------------------------------------------------------------------

// #region pc-register
const searches = new Map(); // body JSON -> Promise<searchid>

/** Register (once) the mosaic search of a source for a time context; resolves to its id. */
function pcSearch(spec, product, ctx) {
  const args = [{ op: "anyinteracts", args: [{ property: "datetime" }, { interval: [ctx.start, ctx.end] }] }, ...(spec.query ?? [])];
  for (const f of product.time?.filters ?? []) {
    const v = ctx.filters?.[f.id];
    if (f.type === "max" && v != null && v < f.max) args.push({ op: "<=", args: [{ property: f.property }, v] });
  }
  const body = JSON.stringify({
    collections: [spec.collection],
    "filter-lang": "cql2-json",
    filter: { op: "and", args },
    sortby: [{ field: "datetime", direction: "desc" }],
  });
  if (!searches.has(body)) {
    const p = fetch(`${spec.api}/mosaic/register`, { method: "POST", headers: { "content-type": "application/json" }, body })
      .then(async (res) => {
        if (!res.ok) throw new Error(`mosaic register: HTTP ${res.status}`);
        return (await res.json()).searchid;
      })
      .catch((err) => {
        searches.delete(body);
        throw err;
      });
    searches.set(body, p);
  }
  return searches.get(body);
}
// #endregion pc-register

// #region pc-tile
/** Asset query parameters (in band order) for the bands a layer reads. */
function pcAssets(spec, bands) {
  const order = [];
  const groups = new Map(); // asset -> [bidx]
  for (const b of bands) {
    const [asset, bidx] = spec.assets[b].split("|");
    if (!groups.has(asset)) {
      groups.set(asset, []);
      order.push(asset);
    }
    if (bidx) groups.get(asset).push(bidx);
  }
  const p = new URLSearchParams();
  for (const a of order) p.append("assets", a);
  for (const a of order) if (groups.get(a).length) p.append("asset_bidx", `${a}|${groups.get(a).join(",")}`);
  // Output band order: by asset, then index
  const outNames = order.flatMap((a) => bands.filter((b) => spec.assets[b].split("|")[0] === a));
  return { params: p, names: outNames };
}

async function pcTile(catalog, product, layer, ctx, { x, y, z }, box, signal) {
  const spec = catalog.sources[layer.source];
  const id = await pcSearch(spec, product, ctx);
  const r = layer.render;
  const bands = r.type === "identity" ? spec.bands.slice(0, 3) : usedBands(r, spec.bands);
  const { params, names } = pcAssets(spec, bands);
  params.set("collection", spec.collection);
  params.set("pixel_selection", ctx.t2 ? (ctx.options?.px ?? "first") : "first");
  const url = `${spec.api}/mosaic/${id}/tiles/WebMercatorQuad/${z}/${x}/${y}@2x.${spec.format}?${params}`;
  const res = await fetchOk(url, { signal }, "Planetary Computer");
  if (!res) return null;
  if (spec.format !== "npy") return imageTile(await res.blob(), r);
  return toImage(r, npyWindow(parseNpy(await res.arrayBuffer()), names, spec, box));
}
// #endregion pc-tile

/** An 8-bit image tile, shown as is (optionally desaturated / lightened). */
async function imageTile(blob, r, size = TILE_SIZE) {
  const rgba = await decodeImage(blob, size, size);
  const win = { rgba, width: size, height: size };
  return toImage(r.type === "identity" ? r : { type: "identity" }, win);
}

// --------------------------------------------------------------------------
// titiler-cmr
// --------------------------------------------------------------------------

// #region titiler-cmr-tile
async function cmrTile(catalog, product, layer, ctx, { x, y, z }, box, signal) {
  const spec = catalog.sources[layer.source];
  const base = env.services[spec.service];
  if (!base) throw new Error(`no "${spec.service}" service in env.json`);
  const iso = (s) => s.replace(".000Z", "Z");
  const p = new URLSearchParams({
    collection_concept_id: spec.concept_id,
    temporal: `${iso(ctx.start)}/${iso(new Date(Date.parse(ctx.end) - 1000).toISOString())}`,
    tilesize: String(TILE_SIZE),
    reproject: "nearest",
    pixel_selection: ctx.t2 ? (ctx.options?.px ?? "first") : "first",
  });
  for (const v of spec.variables) p.append("variables", v);
  if (spec.group) p.set("group", spec.group);
  const res = await fetchOk(`${base}/xarray/tiles/WebMercatorQuad/${z}/${x}/${y}.npy?${p}`, { signal }, "titiler-cmr");
  if (!res) return null;
  const npy = parseNpy(await res.arrayBuffer());
  return toImage(layer.render, npyWindow(npy, spec.variables, spec, box, spec.derive));
}
// #endregion titiler-cmr-tile

// --------------------------------------------------------------------------
// Tile cache (shared by the maps and the animation's pre-loading)
// --------------------------------------------------------------------------

// #region tile-cache
const TILE_CACHE_MAX = 1500; // rendered tiles (512 x 512 RGBA, 1 MB each at most)
const tileCache = new Map(); // key -> Promise<ImageData | ImageBitmap | null>

/** The cached tile, or render(signal) once (failed and aborted renders are not kept). */
function cachedTile(key, render, signal) {
  let p = tileCache.get(key);
  if (p) {
    tileCache.delete(key); // most recently used last
    tileCache.set(key, p);
    return p;
  }
  p = render(signal);
  tileCache.set(key, p);
  p.catch(() => tileCache.delete(key));
  while (tileCache.size > TILE_CACHE_MAX) tileCache.delete(tileCache.keys().next().value);
  return p;
}
// #endregion tile-cache

// --------------------------------------------------------------------------
// Layers
// --------------------------------------------------------------------------

// #region arcgis-layer
/** Deepest tile zoom worth requesting: tile pixels as fine as the source pixels. */
const maxTileZoom = (res) => Math.ceil(Math.log2(CIRCUMFERENCE / (TILE_SIZE * res)) - 1e-6);

const tileBounds = ({ west, south, east, north }) => [west, south, east, north];

/** EPSG:3857 box of tile (x, y, z). */
function tileBox(x, y, z) {
  const span = CIRCUMFERENCE / 2 ** z;
  const o = CIRCUMFERENCE / 2;
  return [x * span - o, o - (y + 1) * span, (x + 1) * span - o, o - y * span];
}

/**
 * How to draw a tiled layer of a product for a time context: {key (cache key
 * prefix), tileSize, maxZoom, render(index, signal) -> ImageData | null}, or
 * null for layers that are not tiled here (COG, CDS, untimed XYZ basemaps).
 */
export function tileRenderer(catalog, product, layer, ctx) {
  const spec = catalog.sources[layer.source];
  const t = ctx?.t ?? null;
  const rkey = JSON.stringify(layer.render);
  if (spec.type === "arcgis") {
    const s = sourceSpec(catalog, layer.source, t);
    return {
      key: `arcgis|${s.url}|${s.band_ids}|${rkey}`,
      tileSize: TILE_SIZE,
      maxZoom: maxTileZoom(s.res),
      render: ({ x, y, z }, signal) => renderArcgisTile(catalog, layer, tileBox(x, y, z), TILE_SIZE, TILE_SIZE, signal, t),
    };
  }
  if (spec.type === "pc-mosaic" || spec.type === "titiler-cmr") {
    if (!ctx) return null;
    const fn = spec.type === "pc-mosaic" ? pcTile : cmrTile;
    return {
      key: `${spec.type}|${layer.source}|${ctx.key}|${rkey}`,
      tileSize: TILE_SIZE,
      maxZoom: spec.max_zoom ?? maxTileZoom(spec.res),
      render: (index, signal) => fn(catalog, product, layer, ctx, index, tileBox(index.x, index.y, index.z), signal),
    };
  }
  if (spec.type === "xyz" && /\{(time|credential):/.test(spec.url)) {
    const url = fillUrl(spec.url, ctx);
    if (url == null) return null;
    return {
      key: `xyz|${url.replace(/api_key=[^&]*/, "")}|${rkey}`,
      tileSize: spec.tile_size,
      maxZoom: spec.max_zoom,
      render: async ({ x, y, z }, signal) => {
        const res = await fetchOk(url.replace("{z}", z).replace("{x}", x).replace("{y}", y), { signal }, "tile");
        return res ? imageTile(await res.blob(), layer.render, spec.tile_size) : null;
      },
    };
  }
  return null;
}

/** A URL template with {time:<param>} and {credential:<name>} filled, or null if one is missing. */
function fillUrl(url, ctx) {
  let missing = false;
  const out = url
    .replace(/\{time:(\w+)\}/g, (_, k) => ctx?.params?.[k] ?? ((missing = true), ""))
    .replace(/\{credential:(\w+)\}/g, (_, k) => encodeURIComponent(credential(k)) || ((missing = true), ""));
  return missing ? null : out;
}

function liveTileLayer(id, catalog, tr, { loading, props, extent, smooth = false }) {
  return new TileLayer({
    id,
    tileSize: tr.tileSize,
    zoomOffset: tr.tileSize === TILE_SIZE ? ZOOM_OFFSET : 0,
    maxZoom: tr.maxZoom,
    extent: extent ?? catalog.lngLatExtent,
    refinementStrategy: "no-overlap",
    maxRequests: 8,
    getTileData: async ({ index, signal }) => {
      loading?.start();
      try {
        const img = await cachedTile(`${tr.key}|${index.z}/${index.x}/${index.y}`, (sig) => tr.render(index, sig), signal);
        loading?.end();
        return img;
      } catch (err) {
        loading?.end(signal?.aborted ? null : err);
        if (!signal?.aborted) console.warn(`${id}: tile failed`, err);
        return null;
      }
    },
    renderSubLayers: (p) =>
      p.data &&
      new BitmapLayer(p, {
        data: null,
        image: p.data,
        bounds: tileBounds(p.tile.bbox),
        textureParameters: smooth ? undefined : { minFilter: "nearest", magFilter: "nearest" },
      }),
    ...props,
  });
}

/**
 * Jobs that fetch and render ahead of time (into the tile cache) the tiles of
 * a product's layers covering `bounds` ([w, s, e, n] degrees) at deck.gl
 * (MapView) zoom `zoom`, as a TileLayer would pick them, for a time context:
 * an array of functions returning promises (run them with a concurrency limit).
 */
export function prefetchTiles(catalog, product, ctx, bounds, zoom, { signal } = {}) {
  const jobs = [];
  for (const layer of product.layers) {
    const tr = tileRenderer(catalog, product, layer, ctx);
    if (!tr) continue;
    const off = tr.tileSize === TILE_SIZE ? ZOOM_OFFSET : 0;
    const z = Math.max(0, Math.min(tr.maxZoom, Math.round(zoom + Math.log2(512 / tr.tileSize)) + off));
    for (const [x, y] of tileRange(bounds, z))
      jobs.push(() => cachedTile(`${tr.key}|${z}/${x}/${y}`, (sig) => tr.render({ x, y, z }, sig), signal).catch(() => null));
  }
  return jobs;
}

/** Slippy tile indices covering a lon / lat box at zoom z. */
function tileRange([w, s, e, n], z) {
  const N = 2 ** z;
  const tx = (lon) => Math.floor(((lon + 180) / 360) * N);
  const ty = (la) => Math.floor(((1 - Math.log(Math.tan(Math.PI / 4 + (la * Math.PI) / 360)) / Math.PI) / 2) * N);
  const out = [];
  for (let y = Math.max(0, ty(n)); y <= Math.min(N - 1, ty(s)); y++)
    for (let x = Math.max(0, tx(w)); x <= Math.min(N - 1, tx(e)); x++) out.push([x, y]);
  return out;
}

function arcgisLayer(id, catalog, product, layer, { loading, props, time }) {
  const tr = tileRenderer(catalog, product, layer, time);
  return liveTileLayer(`${id}|${time?.t ?? ""}`, catalog, tr, { loading, props });
}
// #endregion arcgis-layer

// #region xyz-layers
/** Map tiles, drawn at about their design size (labels too), scaled smoothly. */
function xyzLayers(id, catalog, layer, { props }) {
  const spec = catalog.sources[layer.source];
  const { desaturate = 0, lighten = 0 } = layer.render;
  const layers = [
    new TileLayer({
      id,
      data: spec.url,
      tileSize: spec.tile_size,
      maxZoom: spec.max_zoom,
      extent: catalog.lngLatExtent,
      maxRequests: 8,
      renderSubLayers: (p) =>
        p.data &&
        new BitmapLayer(p, {
          data: null,
          image: p.data,
          bounds: tileBounds(p.tile.bbox),
          desaturate,
        }),
      ...props,
    }),
  ];
  // Lightening (255 - (1 - l) * (255 - v)) is a white veil of opacity l.
  if (lighten) {
    const [w, s, e, n] = catalog.lngLatExtent;
    layers.push(
      new SolidPolygonLayer({
        id: `${id}-lighten`,
        data: [{ polygon: [[w, s], [e, s], [e, n], [w, n]] }], // prettier-ignore
        getPolygon: (d) => d.polygon,
        getFillColor: [255, 255, 255, Math.round(255 * lighten)],
        ...props,
        opacity: lighten * (props.opacity ?? 1),
      }),
    );
  }
  return layers;
}
// #endregion xyz-layers

// #region cds-layer
/**
 * One image of the hour's grid over the area in view (CDS). The grid is
 * requested on first use; `onReady()` is called when it arrives, to redraw.
 */
function cdsLayer(id, catalog, layer, { loading, props, time, view, onReady }) {
  const spec = catalog.sources[layer.source];
  if (!time || !view) return [];
  const area = cdsArea(spec, view);
  const hk = hourKey(time.t);
  const grid = cachedGrid(spec, area, hk);
  if (grid === undefined || grid === null) {
    if (grid === null) return []; // no data for this hour
    const k = `${area}|${hk}`;
    if (!cdsLayer.waiting.has(k)) {
      cdsLayer.waiting.add(k);
      loading?.start();
      cdsGrids(spec, area, [hk], { onStatus: (s) => loading?.note?.(s) })
        .then(() => loading?.end(), (err) => loading?.end(err))
        .finally(() => {
          cdsLayer.waiting.delete(k);
          onReady?.();
        });
    }
    return [];
  }
  return [cdsBitmap(`${id}|${hk}|${area}`, grid, layer.render, props)];
}
cdsLayer.waiting = new Set();

const gridImages = new WeakMap(); // grid -> Map(render JSON -> ImageData)

/** A BitmapLayer of a lat / lon grid colored with a render spec. */
export function cdsBitmap(id, grid, render, props) {
  if (!gridImages.has(grid)) gridImages.set(grid, new Map());
  const cache = gridImages.get(grid);
  const rk = JSON.stringify(render);
  if (!cache.has(rk)) {
    const band = render.band;
    const win = { data: { [band]: grid.values }, width: grid.ni, height: grid.nj, x0: 0, y1: 0, res: 1 };
    cache.set(rk, toImage(render, win));
  }
  const { west, north, di, dj, ni, nj } = grid;
  return new BitmapLayer({
    id,
    image: cache.get(rk),
    bounds: [west - di / 2, north - (nj - 0.5) * dj, west + (ni - 0.5) * di, north + dj / 2],
    textureParameters: { minFilter: "nearest", magFilter: "nearest" },
    ...props,
  });
}
// #endregion cds-layer

// #region product-layers
/**
 * The deck.gl layers of a product, bottom to top (COG layers whose file is
 * still opening are left out until it is open; see onCogOpened).
 * `loading` ({start(), end(error), note(text)}) is told about each tile request.
 * `props(kind)` gives extra props (clip / mask extensions, opacity) for a
 * layer drawn in "lnglat" or deck.gl "common" (COG) coordinates.
 * `time` is the selected time context (slot.js ctx()); `view` the area in
 * view ([w, s, e, n]); `onReady()` is called when data that arrived outside
 * of deck.gl's tile loading (CDS grids) needs a redraw.
 */
export function productLayers(id, catalog, product, { loading, props = () => ({}), time = null, view = null, onReady } = {}) {
  return product.layers.flatMap((layer, i) => {
    const lid = `${id}-${product.id}-${i}`;
    const spec = catalog.sources[layer.source];
    if (spec.type === "cog") return cogLayer(lid, spec, layer, { loading, props: props("common") }) ?? [];
    if (spec.type === "arcgis") return arcgisLayer(lid, catalog, product, layer, { loading, props: props("lnglat"), time });
    if (spec.type === "cds") return cdsLayer(lid, catalog, layer, { loading, props: props("lnglat"), time, view, onReady });
    const tr = tileRenderer(catalog, product, layer, time);
    if (tr) return liveTileLayer(`${lid}|${tr.key}`, catalog, tr, { loading, props: props("lnglat"), smooth: spec.smooth && spec.type === "xyz" });
    if (spec.type === "xyz" && !/\{(time|credential):/.test(spec.url)) return xyzLayers(lid, catalog, layer, { props: props("lnglat") });
    if (spec.type === "xyz" || spec.type === "pc-mosaic" || spec.type === "titiler-cmr") return []; // timestep not resolved yet
    throw new Error(`${layer.source}: unsupported source type ${spec.type}`);
  });
}
// #endregion product-layers
