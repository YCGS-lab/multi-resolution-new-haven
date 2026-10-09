// Tiled rendering of catalog products: one deck.gl layer per product layer.
//
// Layers on a local COG are deck.gl-raster COGLayers (cog.js). Layers on an
// image service are deck.gl TileLayers over Web Mercator tiles:
//
//   - ArcGIS ImageServer: for every tile, an exportImage request for the
//     tile's area at the tile's resolution, colored on the CPU with the
//     layer's render spec (band combination, value range, colormap,
//     hillshade; see scripts/common/web.py).
//   - XYZ map tiles: the tiles themselves, scaled smoothly, optionally
//     desaturated and lightened (as a basemap).
//
// Coordinates: sources and requests use absolute EPSG:3857 meters; deck.gl
// layers use longitude / latitude (MapView).

import { BitmapLayer, GeoTIFF, SolidPolygonLayer, TileLayer } from "../vendor/deck-gl-raster.js";
import { cogLayer } from "./cog.js";

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
}

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

async function decodeImage(blob, w, h) {
  const img = await createImageBitmap(blob);
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  ctx.drawImage(img, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h).data;
}

const arcgisSources = new Map();

function arcgisSource(catalog, id) {
  if (!arcgisSources.has(id)) arcgisSources.set(id, new ArcgisSource(catalog.sources[id]));
  return arcgisSources.get(id);
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

/** RGBA image (ImageData, or null if empty) of an ArcGIS layer over box (EPSG:3857), w x h pixels. */
export async function renderArcgisTile(catalog, layer, box, w, h, signal) {
  const src = arcgisSource(catalog, layer.source);
  const r = layer.render;
  const pad = r.hillshade || (r.shade && !r.shade.precomputed) ? 1 : 0;
  const win = await src.read(box, (box[2] - box[0]) / w, { pad, signal });
  const out = crop(colorize(r, win), win.width, pad, w, h);
  for (let k = 3; k < out.length; k += 4) if (out[k]) return new ImageData(out, w, h);
  return null;
}

/** Deepest tile zoom worth requesting: tile pixels as fine as the source pixels. */
const maxTileZoom = (res) => Math.ceil(Math.log2(CIRCUMFERENCE / (TILE_SIZE * res)) - 1e-6);

const tileBounds = ({ west, south, east, north }) => [west, south, east, north];

function arcgisLayer(id, catalog, layer, { loading, props }) {
  const spec = catalog.sources[layer.source];
  return new TileLayer({
    id,
    tileSize: TILE_SIZE,
    zoomOffset: ZOOM_OFFSET,
    maxZoom: maxTileZoom(spec.res),
    extent: catalog.lngLatExtent,
    refinementStrategy: "no-overlap",
    maxRequests: 8,
    getTileData: async ({ bbox, signal }) => {
      const box = [mercX(bbox.west), mercY(bbox.south), mercX(bbox.east), mercY(bbox.north)];
      loading?.start();
      try {
        const img = await renderArcgisTile(catalog, layer, box, TILE_SIZE, TILE_SIZE, signal);
        loading?.end();
        return img;
      } catch (err) {
        loading?.end(signal?.aborted ? null : err);
        if (!signal?.aborted) console.warn(`${spec.url}: tile failed`, err);
        return null;
      }
    },
    renderSubLayers: (p) =>
      p.data &&
      new BitmapLayer(p, {
        data: null,
        image: p.data,
        bounds: tileBounds(p.tile.bbox),
        textureParameters: { minFilter: "nearest", magFilter: "nearest" },
      }),
    ...props,
  });
}

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

/**
 * The deck.gl layers of a product, bottom to top (COG layers whose file is
 * still opening are left out until it is open; see onCogOpened).
 * `loading` ({start(), end(error)}) is told about each tile request.
 * `props(kind)` gives extra props (clip / mask extensions, opacity) for a
 * layer drawn in "lnglat" or deck.gl "common" (COG) coordinates.
 */
export function productLayers(id, catalog, product, { loading, props = () => ({}) } = {}) {
  return product.layers.flatMap((layer, i) => {
    const lid = `${id}-${product.id}-${i}`;
    const spec = catalog.sources[layer.source];
    if (spec.type === "cog") return cogLayer(lid, spec, layer, { loading, props: props("common") }) ?? [];
    if (spec.type === "arcgis") return arcgisLayer(lid, catalog, layer, { loading, props: props("lnglat") });
    if (spec.type === "xyz") return xyzLayers(lid, catalog, layer, { props: props("lnglat") });
    throw new Error(`${layer.source}: unsupported source type ${spec.type}`);
  });
}
