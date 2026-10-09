// Local Cloud-Optimized GeoTIFFs, drawn with deck.gl-raster's COGLayer.
//
// deck.gl-raster reads the COG (header, overview choice, tile fetching with
// range requests, decoding in a worker pool) and draws each COG tile as a
// textured mesh. What it does not know is our render specs (see
// scripts/common/web.py), so each COG layer brings its own `getTileData`,
// which uploads the bands the spec reads as a float texture, and its own
// `renderTile`, whose shader module is generated from the spec: band
// expressions, stretches, colormaps (with under / over colors), categorical
// colors, a stored hillshade, and growing sparse pixels (dilate_px). All of
// it runs on the GPU, per screen pixel, with nearest-neighbor sampling, so
// native pixels stay sharp blocks.
//
// Coordinates: the COGs are EPSG:3857 and deck.gl-raster draws them in deck.gl
// common space (Web Mercator, 512 units around the world), under a MapView.

import { COGLayer, DecoderPool, GeoTIFF, PerOriginSemaphore, parseWkt } from "../vendor/deck-gl-raster.js";

// Every COG is EPSG:3857; resolve it locally (the default resolver asks epsg.io).
const WKT_3857 =
  'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],' +
  'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],' +
  'PARAMETER["scale_factor",1],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],' +
  'EXTENSION["PROJ4","+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs"],' +
  'AUTHORITY["EPSG","3857"]]';
const proj3857 = parseWkt(WKT_3857);
async function epsgResolver(code) {
  if (code !== 3857) throw new Error(`EPSG:${code}: only EPSG:3857 COGs are supported`);
  return proj3857;
}

// Tiles are decoded (LERC, JPEG, DEFLATE) in workers.
const pool = new DecoderPool({
  createWorker: () => new Worker(new URL("../vendor/geotiff-worker.js", import.meta.url), { type: "module" }),
});
// At most 6 concurrent range requests per origin (the HTTP/1.1 browser limit).
const limiter = new PerOriginSemaphore({ maxRequests: 6 });

// No-data pixels are uploaded as this value (the shaders treat anything below -1e38 as no data).
const NODATA_GPU = -3e38;

// --------------------------------------------------------------------------
// Opening COGs: one GeoTIFF (header) per URL, shared by every layer using it
// --------------------------------------------------------------------------

const opened = new Map(); // url -> {tiff: GeoTIFF | null, promise}
const openListeners = new Set();

/** Call `fn` whenever a COG finishes opening (so maps can add its layers). */
export function onCogOpened(fn) {
  openListeners.add(fn);
}

/** The opened GeoTIFF for a source, or null while it is opening (or failed). */
function geotiff(spec) {
  const url = new URL(spec.url, document.baseURI).href;
  if (!opened.has(url)) {
    const entry = { tiff: null };
    entry.promise = GeoTIFF.fromUrl(url, { concurrencyLimiter: limiter }).then(
      (tiff) => {
        entry.tiff = tiff;
        openListeners.forEach((fn) => fn());
      },
      (err) => console.error(`${url}: could not open COG`, err),
    );
    opened.set(url, entry);
  }
  return opened.get(url).tiff;
}

// --------------------------------------------------------------------------
// Tile data: the bands a render spec reads, as one texture
// --------------------------------------------------------------------------

/** One typed array per band, from any layout the decoder returns. */
function bandArrays(array, n) {
  if (array.layout === "pixel-interleaved") {
    const { data, count } = array;
    if (count === 1) return [data];
    return Array.from({ length: count }, (_, b) => {
      const out = new data.constructor(n);
      for (let k = 0; k < n; k++) out[k] = data[k * count + b];
      return out;
    });
  }
  // Multi-band LERC (GDAL stores pixel-interleaved bands as LERC "depth")
  // decodes to ONE array holding every band in turn.
  if (array.bands.length === 1 && array.count > 1) {
    return Array.from({ length: array.count }, (_, b) => array.bands[0].subarray(b * n, (b + 1) * n));
  }
  return array.bands;
}

/** Copy the top-left w x h pixels of a W-wide band (edge tiles are partly outside the image). */
function clip(band, W, w, h) {
  if (w === W && band.length === w * h) return band;
  const out = new band.constructor(w * h);
  for (let i = 0; i < h; i++) out.set(band.subarray(i * W, i * W + w), i * w);
  return out;
}

const SAMPLER = {
  minFilter: "nearest",
  magFilter: "nearest",
  addressModeU: "clamp-to-edge",
  addressModeV: "clamp-to-edge",
};

/**
 * Reads tile (x, y) of a COG level and uploads the bands `prog` reads:
 * 8-bit RGB for "rgba8" programs, else up to four bands as float32 with
 * no data as NODATA_GPU. Resolves to null for tiles without any data.
 */
async function loadTile(image, { device, x, y, signal, pool }, prog, spec) {
  const { array } = await image.fetchTile(x, y, { boundless: true, pool, signal });
  const W = array.width;
  const w = Math.min(W, image.width - x * image.tileWidth);
  const h = Math.min(array.height, image.height - y * image.tileHeight);
  const all = bandArrays(array, W * array.height);
  const bands = prog.bands.map((b) => clip(all[spec.bands.indexOf(b)], W, w, h));
  const n = w * h;
  let data;
  let format;
  if (prog.texture === "rgba8") {
    data = new Uint8Array(n * 4);
    for (let k = 0; k < n; k++) {
      data[k * 4] = bands[0][k];
      data[k * 4 + 1] = bands[1][k];
      data[k * 4 + 2] = bands[2][k];
      data[k * 4 + 3] = 255;
    }
    format = "rgba8unorm";
  } else {
    const nc = bands.length === 1 ? 1 : bands.length === 2 ? 2 : 4;
    const nd = spec.nodata;
    // Float COGs store no data as -9999 (LERC is lossy, so compare loosely).
    const isNodata = nd == null ? () => false : nd <= -9000 ? (v) => v < nd + 1 : (v) => v === nd;
    data = new Float32Array(n * nc);
    let any = false;
    bands.forEach((band, c) => {
      for (let k = 0; k < n; k++) {
        const v = band[k];
        const bad = isNodata(v) || Number.isNaN(v);
        data[k * nc + c] = bad ? NODATA_GPU : v;
        any ||= !bad;
      }
    });
    if (!any) return null;
    format = ["r32float", "rg32float", null, "rgba32float"][nc - 1];
  }
  const texture = device.createTexture({ data, format, width: w, height: h, sampler: SAMPLER });
  return { texture, width: w, height: h, byteLength: data.byteLength };
}

// --------------------------------------------------------------------------
// Render specs -> GLSL
// --------------------------------------------------------------------------

const MATH = { log10: "log10_", log: "log", exp: "exp", sqrt: "sqrt", abs: "abs", min: "min", max: "max", pow: "pow" };

/** A band expression ("hh - hv", "10 * log10(b)") as GLSL over the texel `v`. */
function glslExpr(expr, bandIndex) {
  if (/[^\w\s.+\-*/(),]|\*\*/.test(expr)) throw new Error(`unsupported expression: ${expr}`);
  return expr.replace(/\b\d+\.?\d*(?:[eE][-+]?\d+)?\b|\b[A-Za-z_]\w*\b/g, (tok) => {
    if (/^\d/.test(tok)) return /[.eE]/.test(tok) ? tok : `${tok}.0`; // GLSL needs float literals
    if (tok in bandIndex) return `v.${"rgba"[bandIndex[tok]]}`;
    if (tok in MATH) return MATH[tok];
    throw new Error(`unknown name ${tok} in expression: ${expr}`);
  });
}

const identifiers = (expr) => expr.match(/[A-Za-z_]\w*/g) ?? [];

const hexRgba = (hex) => {
  const h = hex.replace("#", "");
  const n = (i) => parseInt(h.slice(i, i + 2), 16) / 255;
  return [n(0), n(2), n(4), h.length >= 8 ? n(6) : 1];
};
const vec4 = (c) => `vec4(${c.map((x) => x.toFixed(6)).join(", ")})`;
const f = (x) => Number(x).toPrecision(9).replace(/^(-?\d+)$/, "$1.0");

/** GLSL (statements) leaving the 0-1 normalized value of `x` in `t`, as normalizer() in tiles.js. */
function normalizeGlsl(r, x) {
  const g = 1 / (r.gamma ?? 1);
  let s;
  if (r.scale === "log") {
    const l0 = Math.log(r.vmin);
    s = `float t = ${x} <= 0.0 ? -1.0 : (log(${x}) - ${f(l0)}) / ${f(Math.log(r.vmax) - l0)};`;
  } else {
    const lo = r.vmin ?? r.min;
    s = `float t = (${x} - ${f(lo)}) / ${f((r.vmax ?? r.max) - lo)};`;
  }
  if (g !== 1) s += ` if (t > 0.0 && t < 1.0) t = pow(t, ${f(g)});`;
  return s;
}

/** Colors of a colormap or categorical spec as a 256 x 1 RGBA8 lookup texture. */
function lutData(r) {
  const out = new Uint8Array(256 * 4);
  const set = (i, hex) => out.set(hexRgba(hex).map((c) => Math.round(c * 255)), i * 4);
  if (r.type === "colormap") {
    if (r.colors.length !== 256) throw new Error("colormaps need 256 colors");
    r.colors.forEach((c, i) => set(i, c));
  } else {
    for (const [code, c] of Object.entries(r.colors)) {
      const i = Number(code);
      if (!Number.isInteger(i) || i < 0 || i > 255) throw new Error(`categorical code ${code} is not 0-255`);
      set(i, c);
    }
  }
  return out;
}

let nextModule = 0;

/**
 * Compile a layer's render spec for a COG source: the bands its tiles upload,
 * and a deck.gl-raster shader module that colors them. The module samples the
 * tile texture itself (rather than following deck.gl-raster's CreateTexture)
 * so that dilate_px can look at neighboring pixels.
 */
function compile(layer, spec, tiff) {
  const r = layer.render;
  const id = nextModule++;
  const T = `cogBands${id}`;
  const L = `cogLut${id}`;
  const { bitsPerSample, sampleFormat } = tiff.cachedTags;
  const isUint8 = bitsPerSample[0] === 8 && sampleFormat[0] === 1; // e.g. JPEG imagery
  let bands;
  let body; // GLSL: vec4 v (the texel) -> vec4 c (alpha 0 = transparent)
  let lut = null;
  let texture = "float";

  if (r.type === "identity") {
    bands = spec.bands.slice(0, 3);
    if (isUint8) {
      texture = "rgba8";
      body = "vec4 c = v;";
    } else {
      body = "vec4 c = (v.r < -1e38 || v.g < -1e38 || v.b < -1e38) ? vec4(0.0) : vec4(v.rgb / 255.0, 1.0);";
    }
    const { desaturate: ds = 0, lighten: lt = 0 } = r;
    if (ds || lt)
      body += ` float gray = dot(c.rgb, vec3(0.299, 0.587, 0.114));
        c.rgb = 1.0 - ${f(1 - lt)} * (1.0 - mix(c.rgb, vec3(gray), ${f(ds)}));`;
  } else {
    // Bands the spec reads, in texture channel order.
    const names = new Set();
    const add = (v) => (v.band ? names.add(v.band) : identifiers(v.expr).forEach((n) => spec.bands.includes(n) && names.add(n)));
    if (r.type === "rgb") r.channels.forEach(add);
    else add(r);
    if (r.hillshade || (r.shade && !r.shade.precomputed))
      throw new Error("hillshades computed in the browser are not supported for COGs; store the hillshade as a band");
    if (r.shade) names.add(r.shade.band);
    bands = [...names];
    if (bands.length > 4) throw new Error(`a COG layer can read at most 4 bands (${bands})`);
    const index = Object.fromEntries(bands.map((b, i) => [b, i]));
    const ch = (b) => `v.${"rgba"[index[b]]}`;
    // A value (band or expression) and whether every band it reads has data.
    const value = (v) => {
      const used = v.band ? [v.band] : identifiers(v.expr).filter((n) => n in index);
      return {
        x: v.band ? ch(v.band) : `(${glslExpr(v.expr, index)})`,
        ok: used.map((b) => `${ch(b)} > -1e38`).join(" && ") || "true",
      };
    };

    if (r.type === "rgb") {
      const cs = r.channels.map(value);
      body = `vec4 c = vec4(0.0);
        if (${cs.map((c) => `(${c.ok})`).join(" && ")}) {
          ${cs.map((c, i) => `{ float x = ${c.x}; ${normalizeGlsl(r.channels[i], "x")} c.${"rgb"[i]} = clamp(t, 0.0, 1.0); }`).join("\n          ")}
          c.a = 1.0;
        }`;
    } else if (r.type === "categorical") {
      lut = lutData(r);
      const v = value(r);
      body = `vec4 c = vec4(0.0);
        if (${v.ok}) {
          float x = ${v.x};
          if (x >= 0.0 && x <= 255.0 && x == floor(x)) c = textureLod(${L}, vec2((x + 0.5) / 256.0, 0.5), 0.0);
        }`;
    } else if (r.type === "colormap") {
      lut = lutData(r);
      const v = value(r);
      const shade = r.shade
        ? `{ float hs = ${ch(r.shade.band)}; c.rgb *= ${f(1 - r.shade.strength)} + ${f(r.shade.strength)} * (hs > -1e38 ? hs : 1.0); }`
        : "";
      body = `vec4 c = vec4(0.0);
        if (${v.ok}) {
          float x = ${v.x};
          ${normalizeGlsl(r, "x")}
          c = t < 0.0 ? ${vec4(hexRgba(r.under))} : t > 1.0 ? ${vec4(hexRgba(r.over))}
            : textureLod(${L}, vec2((min(255.0, floor(t * 256.0)) + 0.5) / 256.0, 0.5), 0.0);
          ${shade}
        }`;
    } else {
      throw new Error(`unsupported render type ${r.type}`);
    }
  }

  // Grow data pixels into transparent ones within dilate_px pixels, taking
  // the nearest in the same row, else in the nearest row (as dilate(): a
  // horizontal, then a vertical pass). Offsets are in screen pixels (device
  // pixels; the CPU renderer used tile pixels, 0.7-1.4 screen pixels).
  // Pixels in neighboring tiles are not seen, so growth stops at tile edges.
  const R = layer.dilate_px || 0;
  const main = R
    ? `vec2 du = dFdx(geometry.uv), dv = dFdy(geometry.uv);
      vec4 c = cogColor${id}(geometry.uv);
      for (int a = 0; a <= ${R} && c.a == 0.0; a++)
        for (int sa = -1; sa <= 1 && c.a == 0.0; sa += 2)
          for (int b = 0; b <= ${R} && c.a == 0.0; b++)
            for (int sb = -1; sb <= 1 && c.a == 0.0; sb += 2) {
              if ((a == 0 && sa == 1) || (b == 0 && sb == 1) || (a == 0 && b == 0)) continue;
              vec2 uv = geometry.uv + float(sb * b) * du + float(sa * a) * dv;
              if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) c = cogColor${id}(uv);
            }`
    : `vec4 c = cogColor${id}(geometry.uv);`;

  const module = {
    name: `cogRender${id}`,
    inject: {
      "fs:#decl": `
precision highp sampler2D;
uniform sampler2D ${T};
${lut ? `uniform sampler2D ${L};` : ""}
float log10_(float x) { return log(x) * 0.4342944819032518; }
vec4 cogColor${id}(vec2 uv) {
  vec4 v = textureLod(${T}, uv, 0.0);
  ${body}
  return c;
}`,
      "fs:DECKGL_FILTER_COLOR": `
  ${main}
  if (c.a == 0.0) discard;
  color = c;`,
    },
    getUniforms: (p) => ({ [T]: p.bands, ...(lut ? { [L]: p.lut } : {}) }),
  };
  return { bands, texture, lut, module };
}

const programs = new WeakMap(); // layer spec -> compiled program

function program(layer, spec, tiff) {
  if (!programs.has(layer)) programs.set(layer, compile(layer, spec, tiff));
  return programs.get(layer);
}

const lutTextures = new WeakMap(); // program -> Texture

function lutTexture(prog, device) {
  if (!lutTextures.has(prog))
    lutTextures.set(prog, device.createTexture({ data: prog.lut, format: "rgba8unorm", width: 256, height: 1, sampler: SAMPLER }));
  return lutTextures.get(prog);
}

/**
 * The deck.gl layer for one product layer on a COG source, or null while the
 * COG is opening. `loading` ({start(), end(error)}) is told about each tile
 * request; `props` (e.g. clip / mask extensions, opacity) go to the layer.
 */
export function cogLayer(id, spec, layer, { loading, props = {} } = {}) {
  const tiff = geotiff(spec);
  if (!tiff) return null;
  const prog = program(layer, spec, tiff);
  return new COGLayer({
    id,
    geotiff: tiff,
    epsgResolver,
    pool,
    maxRequests: 8,
    refinementStrategy: "no-overlap",
    getTileData: async (image, opts) => {
      loading?.start();
      try {
        const data = await loadTile(image, opts, prog, spec);
        if (data && prog.lut) data.lut = lutTexture(prog, opts.device);
        loading?.end();
        return data;
      } catch (err) {
        loading?.end(opts.signal?.aborted ? null : err);
        if (!opts.signal?.aborted) console.warn(`${spec.url}: tile failed`, err);
        return null;
      }
    },
    renderTile: (data) => ({ renderPipeline: [{ module: prog.module, props: { bands: data.texture, lut: data.lut } }] }),
    onTileUnload: (tile) => tile.content?.texture?.destroy(),
    ...props,
  });
}
