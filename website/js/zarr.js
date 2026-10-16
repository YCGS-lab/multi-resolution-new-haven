// Gridded data from Analysis-Ready, Cloud-Optimised (ARCO) Zarr stores, read
// in the browser with zarrita (website/vendor/zarrita.js, loaded on first
// use): ERA5-Land from ECMWF's stores, with the user's CDS API key as a
// bearer token.
//
// ECMWF publishes each store twice: geo-chunked (long time series at a
// point) and time-chunked (large areas over short periods). Maps use the
// time-chunked store: one map hour touches few chunks, each covering a large
// area. Only the chunks overlapping the area in view are fetched, and fetched
// chunks are kept (ByteLRU), so panning and the animation reuse them.
//
// Arrays: a variable over (time, latitude, longitude) in any order (from
// _ARRAY_DIMENSIONS / dimension_names), 1-D coordinates `time` (CF units,
// e.g. "hours since 1900-01-01"), `latitude`, `longitude` (either order /
// convention).

import { credential } from "./env.js";

let lib = null;
const zarrita = () => (lib ??= import("../vendor/zarrita.js"));

// #region byte-lru
/** Store byte cache with a size limit (least recently used out first). */
class ByteLRU {
  constructor(maxBytes) {
    this.max = maxBytes;
    this.bytes = 0;
    this.map = new Map();
  }

  has(k) {
    return this.map.has(k);
  }

  get(k) {
    const v = this.map.get(k);
    if (v !== undefined || this.map.has(k)) {
      this.map.delete(k);
      this.map.set(k, v);
    }
    return v;
  }

  set(k, v) {
    if (this.map.has(k)) this.bytes -= this.map.get(k)?.byteLength ?? 0;
    this.map.set(k, v);
    this.bytes += v?.byteLength ?? 0;
    while (this.bytes > this.max && this.map.size > 1) {
      const [old, ov] = this.map.entries().next().value;
      this.map.delete(old);
      this.bytes -= ov?.byteLength ?? 0;
    }
    return this;
  }
}
const chunkCache = new ByteLRU(400e6);
// #endregion byte-lru

// --------------------------------------------------------------------------
// Opening a store
// --------------------------------------------------------------------------

const datasets = new Map(); // url|key -> Promise<dataset>
let fetches = 0; // chunk / metadata requests made (for progress)

/** Turn an HTTP error from the store into something the user can act on. */
function explain(err) {
  const m = /status (\d+)/.exec(err?.message ?? "");
  if (m?.[1] === "401") return new Error("the store rejected the API key (check your CDS key under Credentials)");
  if (m?.[1] === "403") return new Error("access refused (accept the dataset's licence on the CDS website)");
  if (m?.[1] === "429") return new Error("rate limited by the store: try again in a little while");
  return err;
}

// #region open-dataset
/**
 * Open a source's store (once per key): the variable, its dimension order,
 * coordinates and time axis.
 */
export function openDataset(spec) {
  const key = credential(spec.credential);
  if (!key) return Promise.reject(new Error("no API key"));
  const id = `${spec.url}|${key.slice(-6)}`;
  if (!datasets.has(id)) {
    const p = open(spec, key).catch((err) => {
      datasets.delete(id);
      throw explain(err);
    });
    datasets.set(id, p);
  }
  return datasets.get(id);
}

async function open(spec, key) {
  const z = await zarrita();
  let store = new z.FetchStore(spec.url, {
    overrides: { headers: { Authorization: `Bearer ${key}` } },
    fetch: (req) => {
      fetches++;
      return fetch(req);
    },
  });
  store = z.withByteCaching(store, { cache: chunkCache });
  store = await z.withMaybeConsolidatedMetadata(store);
  const root = await z.open(store, { kind: "group" });
  const openArray = (name) => z.open(root.resolve(name), { kind: "array" });
  let arr = null;
  for (const name of spec.variables) {
    try {
      arr = await openArray(name);
      break;
    } catch {
      // try the next name
    }
  }
  if (!arr) throw new Error(`none of ${spec.variables.join(", ")} in ${spec.url}`);
  const dims = arr.attrs?._ARRAY_DIMENSIONS ?? arr.dimensionNames ?? ["time", "latitude", "longitude"];
  const axis = (names) => dims.findIndex((d) => names.includes(d));
  const order = { time: axis(["time", "valid_time"]), lat: axis(["latitude", "lat"]), lon: axis(["longitude", "lon"]) };
  if (Object.values(order).some((i) => i < 0) || dims.length !== 3) throw new Error(`unexpected dimensions ${dims}`);
  const coord = async (names) => {
    for (const n of names) {
      try {
        return await openArray(n);
      } catch {
        // next
      }
    }
    throw new Error(`no ${names[0]} coordinate`);
  };
  const lat = Float64Array.from((await z.get(await coord([dims[order.lat]]))).data, Number);
  const lon = Float64Array.from((await z.get(await coord([dims[order.lon]]))).data, Number);
  const timeArr = await coord([dims[order.time]]);
  const n = timeArr.shape[0];
  const at = async (i) => Number((await z.get(timeArr, [z.slice(i, i + 1)])).data[0]);
  const toMs = timeDecoder(timeArr.attrs ?? {});
  const t0 = toMs(await at(0));
  const dt = n > 1 ? toMs(await at(1)) - t0 : 3600e3;
  const tLast = toMs(await at(n - 1));
  const attrs = arr.attrs ?? {};
  return {
    z,
    arr,
    order,
    lat,
    lon,
    time: { t0, dt, n, tLast, at: async (i) => toMs(await at(i)) },
    scale: attrs.scale_factor ?? 1,
    offset: attrs.add_offset ?? 0,
    fill: attrs._FillValue ?? attrs.missing_value ?? arr.fillValue,
  };
}
// #endregion open-dataset

/** CF time ("<unit> since <date>") -> ms since 1970; without units, nanoseconds (datetime64[ns]). */
function timeDecoder(attrs) {
  const m = /^\s*(\w+)\s+since\s+(.+?)\s*$/.exec(attrs.units ?? "");
  if (!m) return (v) => v / 1e6;
  const unit = { seconds: 1e3, second: 1e3, s: 1e3, minutes: 60e3, minute: 60e3, hours: 3600e3, hour: 3600e3, h: 3600e3, days: 86400e3, day: 86400e3, d: 86400e3, milliseconds: 1, nanoseconds: 1e-6 }[m[1].toLowerCase()];
  if (!unit) throw new Error(`unsupported time units ${attrs.units}`);
  let ref = m[2].replace(" ", "T");
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(ref)) ref += "Z";
  if (/^\d{4}-\d{2}-\d{2}T?Z$/.test(ref)) ref = ref.replace(/T?Z$/, "T00:00:00Z");
  const base = Date.parse(ref);
  if (Number.isNaN(base)) throw new Error(`unsupported time reference ${attrs.units}`);
  return (v) => base + v * unit;
}

/** The first and last hour of a source's store (for the time control). */
export async function zarrTimeRange(spec) {
  const ds = await openDataset(spec);
  return [new Date(ds.time.t0), new Date(ds.time.tLast)];
}

// --------------------------------------------------------------------------
// Reading grids
// --------------------------------------------------------------------------

// #region zarr-area
/**
 * The area to read for a view (lon / lat box): the view grown by a quarter
 * on each side and snapped to whole degrees, at most max_area_deg a side,
 * so small pans reuse earlier reads.
 */
export function zarrArea(spec, [w, s, e, n]) {
  const grow = (lo, hi) => {
    const c = (lo + hi) / 2;
    const half = Math.min(spec.max_area_deg, Math.max(1, (hi - lo) * 1.5)) / 2;
    return [Math.floor(c - half), Math.ceil(c + half)];
  };
  const [w2, e2] = grow(w, e);
  const [s2, n2] = grow(s, n);
  return [Math.max(-180, w2), Math.max(-90, s2), Math.min(180, e2), Math.min(90, n2)];
}
// #endregion zarr-area

const grids = new Map(); // `${url}|${area}|${hourKey}` -> grid | null (no data)

/** A grid already read; null: no data for that hour; undefined: not read yet. */
export function cachedGrid(spec, area, hourKey) {
  const k = `${spec.url}|${area}|${hourKey}`;
  return grids.has(k) ? grids.get(k) : undefined;
}

/** Index range [i0, i1] of the coordinate values within [lo, hi] (plus one cell on each side). */
function range(values, lo, hi) {
  let i0 = Infinity;
  let i1 = -Infinity;
  for (let i = 0; i < values.length; i++)
    if (values[i] >= lo && values[i] <= hi) {
      i0 = Math.min(i0, i);
      i1 = Math.max(i1, i);
    }
  if (i0 > i1) return null;
  return [Math.max(0, i0 - 1), Math.min(values.length - 1, i1 + 1)];
}

// #region zarr-grids
/**
 * Grids for the given hours ("YYYY-MM-DDTHH:00Z") over `area` ([w, s, e, n]):
 * Map hourKey -> {ni, nj, west, north, di, dj, values (north -> south rows,
 * NaN = no data)} or null. Hours are read in runs of consecutive time
 * indices, one zarrita read per run. `onProgress(done, total)` counts the
 * store's chunk requests; `signal` stops between runs (runs already read are kept).
 */
export async function zarrGrids(spec, area, hourKeys, { onProgress, signal } = {}) {
  const ds = await openDataset(spec);
  const { z, arr, order, lat, lon, time } = ds;
  const todo = [...new Set(hourKeys)].filter((h) => cachedGrid(spec, area, h) === undefined);
  if (todo.length) {
    // Longitudes in the store's convention (0-360 or -180-180).
    const lon360 = lon[lon.length - 1] > 180;
    const [w, s, e, n] = area;
    const lonR = lon360 && w < 0 && e <= 0 ? range(lon, w + 360, e + 360) : range(lon, w, e);
    const latR = range(lat, s, n);
    const idx = todo.map((h) => ({ h, i: Math.round((Date.parse(h.replace("Z", ":00Z")) - time.t0) / time.dt) }));
    for (const { h, i } of idx) if (!(i >= 0 && i < time.n) || !lonR || !latR) grids.set(`${spec.url}|${area}|${h}`, null);
    const valid = idx.filter(({ i }) => i >= 0 && i < time.n && lonR && latR).sort((a, b) => a.i - b.i);
    // Runs of equally spaced indices (consecutive hours, or every N hours), at most a day apart
    const runs = [];
    for (const v of valid) {
      const r = runs.at(-1);
      const d = r ? v.i - r.items.at(-1).i : 0;
      if (r && d > 0 && d <= 24 && (r.items.length === 1 || d === r.step)) {
        if (r.items.length === 1) r.step = d;
        r.items.push(v);
      } else if (!r || d !== 0) runs.push({ items: [v], step: 1 });
    }
    // Progress: chunks overlapping the reads (store requests are counted as they happen).
    const chunkCount = (a, b, c) => Math.floor(b / c) - Math.floor(a / c) + 1;
    const ch = arr.chunks;
    const total = runs.reduce(
      (sum, r) =>
        sum +
        new Set(r.items.map(({ i }) => Math.floor(i / ch[order.time]))).size *
          chunkCount(latR[0], latR[1], ch[order.lat]) *
          chunkCount(lonR[0], lonR[1], ch[order.lon]),
      0,
    );
    const start = fetches;
    const timer = onProgress && setInterval(() => onProgress(Math.min(total, fetches - start), total), 250);
    try {
      for (const r of runs) {
        signal?.throwIfAborted();
        const first = r.items[0].i;
        const last = r.items.at(-1).i;
        const sel = [];
        sel[order.time] = z.slice(first, last + 1, r.step);
        sel[order.lat] = z.slice(latR[0], latR[1] + 1);
        sel[order.lon] = z.slice(lonR[0], lonR[1] + 1);
        const out = await z.get(arr, sel).catch((err) => {
          throw explain(err);
        });
        for (const { h, i } of r.items) grids.set(`${spec.url}|${area}|${h}`, toGrid(ds, spec, out, (i - first) / r.step, latR, lonR, lon360));
      }
    } finally {
      if (timer) clearInterval(timer);
      onProgress?.(total, total);
    }
  }
  return new Map(hourKeys.map((h) => [h, cachedGrid(spec, area, h)]));
}
// #endregion zarr-grids

/** One time step of a read as a north-up grid (with the source's offset, e.g. K -> deg C). */
function toGrid(ds, spec, out, ti, latR, lonR, lon360) {
  const { order, lat, lon, scale, offset, fill } = ds;
  const nj = latR[1] - latR[0] + 1;
  const ni = lonR[1] - lonR[0] + 1;
  const [st, sl, sn] = [out.stride[order.time], out.stride[order.lat], out.stride[order.lon]];
  const latAsc = lat[latR[1]] > lat[latR[0]];
  const values = new Float32Array(ni * nj);
  let any = false;
  for (let j = 0; j < nj; j++) {
    const jj = latAsc ? nj - 1 - j : j; // row j of the output is the j-th from the north
    for (let i = 0; i < ni; i++) {
      const v = Number(out.data[ti * st + jj * sl + i * sn]);
      const ok = Number.isFinite(v) && v !== fill;
      values[j * ni + i] = ok ? v * scale + offset + (spec.offset ?? 0) : NaN;
      any ||= ok;
    }
  }
  if (!any) return null;
  let west = lon[lonR[0]];
  if (lon360 && west >= 180) west -= 360;
  return {
    ni,
    nj,
    west,
    north: Math.max(lat[latR[0]], lat[latR[1]]),
    di: Math.abs(lon[Math.min(lon.length - 1, lonR[0] + 1)] - lon[lonR[0]]),
    dj: Math.abs(lat[Math.min(lat.length - 1, latR[0] + 1)] - lat[latR[0]]),
    values,
  };
}

/** The hour key of a time context's timestep. */
export const hourKey = (t) => `${t.slice(0, 13)}:00Z`;
