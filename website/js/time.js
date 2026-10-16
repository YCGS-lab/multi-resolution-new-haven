// Timesteps: their keys, and which ones have data over the area in view.
//
// A product's `time` spec (scripts/common/web.py time_spec) gives the step
// and where the list of timesteps comes from. Keys are strings by step:
//   year "2023", month "2026-07", day "2026-07-20",
//   hour / time "2026-07-20T14:00Z" (UTC).
// availability() returns, for a product and a lon / lat box, a Steps object
// (or HourlySteps for an every-hour list): the sorted keys with data there,
// with per-timestep URL parameters and image properties (e.g. cloud cover,
// for the filters).

import { credential } from "./env.js";

// --------------------------------------------------------------------------
// Keys
// --------------------------------------------------------------------------

const pad = (n, w = 2) => String(n).padStart(w, "0");
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// #region time-keys
/** Start of a timestep (UTC Date). */
export function keyStart(key, step) {
  if (step === "year") return new Date(Date.UTC(+key, 0, 1));
  if (step === "month") return new Date(Date.UTC(+key.slice(0, 4), +key.slice(5, 7) - 1, 1));
  if (step === "day") return new Date(`${key}T00:00:00Z`);
  return new Date(key.replace("Z", ":00Z"));
}

/** End of a timestep (exclusive). */
export function keyEnd(key, step) {
  const d = keyStart(key, step);
  if (step === "year") d.setUTCFullYear(d.getUTCFullYear() + 1);
  else if (step === "month") d.setUTCMonth(d.getUTCMonth() + 1);
  else if (step === "day") d.setUTCDate(d.getUTCDate() + 1);
  else if (step === "hour") d.setUTCHours(d.getUTCHours() + 1);
  else d.setUTCMinutes(d.getUTCMinutes() + 1);
  return d;
}

/** Key of the timestep containing a Date. */
export function dateKey(d, step) {
  const y = d.getUTCFullYear();
  if (step === "year") return String(y);
  const m = `${y}-${pad(d.getUTCMonth() + 1)}`;
  if (step === "month") return m;
  const day = `${m}-${pad(d.getUTCDate())}`;
  if (step === "day") return day;
  return `${day}T${pad(d.getUTCHours())}:${step === "hour" ? "00" : pad(d.getUTCMinutes())}Z`;
}

/** Key of an ISO datetime string (e.g. a STAC item's). */
export const isoKey = (iso, step) => dateKey(new Date(iso), step);

/** Day ("YYYY-MM-DD") of a key with a day. */
export const dayOf = (key) => key.slice(0, 10);

/** Readable timestep, e.g. "18 Sep 2026", "July 2026", "20 Jul 2026, 14:00 UTC". */
export function keyLabel(key, step, { short = false } = {}) {
  if (!key) return "";
  if (step === "year") return key;
  const y = key.slice(0, 4);
  const mo = +key.slice(5, 7) - 1;
  if (step === "month") return `${short ? MONTHS[mo].slice(0, 3) : MONTHS[mo]} ${y}`;
  const day = `${+key.slice(8, 10)} ${MONTHS[mo].slice(0, 3)} ${y}`;
  if (step === "day") return day;
  return `${day}, ${key.slice(11, 16)} UTC`;
}

/** The interval of a timestep or window as ISO strings [start, end). */
export function interval(t, t2, step) {
  return [keyStart(t, step).toISOString(), keyEnd(t2 ?? t, step).toISOString()];
}

/** Days between the starts of two keys. */
export const daysBetween = (a, b, step) => (keyStart(b, step) - keyStart(a, step)) / 86400e3;
// #endregion time-keys

// --------------------------------------------------------------------------
// Sets of timesteps
// --------------------------------------------------------------------------

// #region steps
/** A sorted set of timesteps: {key, label?, params?, items?: [properties]}. */
export class Steps {
  constructor(step, entries) {
    this.step = step;
    this.map = new Map(entries.map((e) => [e.key, e]));
    this.keys = [...this.map.keys()].sort();
    this.dayset = new Set(this.keys.map((k) => k.slice(0, 10)));
    this.monthset = new Set(this.keys.map((k) => k.slice(0, 7)));
  }

  get size() {
    return this.keys.length;
  }

  get(key) {
    return this.map.get(key) ?? null;
  }

  has(key) {
    return this.map.has(key);
  }

  latest() {
    return this.keys.at(-1) ?? null;
  }

  first() {
    return this.keys[0] ?? null;
  }

  /** Nearest timestep before (d < 0) or after (d > 0) `key` (which need not be in the set). */
  neighbor(key, d) {
    if (!key) return d < 0 ? this.latest() : null;
    const i = lowerBound(this.keys, key);
    if (d < 0) return this.keys[i - 1] ?? null;
    return this.keys[this.keys[i] === key ? i + 1 : i] ?? null;
  }

  /** Timesteps in [a, b] (keys). */
  between(a, b) {
    return this.keys.slice(lowerBound(this.keys, a), lowerBound(this.keys, b + "￿"));
  }

  hasDay(day) {
    return this.dayset.has(day);
  }

  hasMonth(month) {
    return this.monthset.has(month);
  }

  /** Timesteps on a day. */
  inDay(day) {
    return this.between(day, day);
  }

  /** The timesteps whose entry passes `fn`. */
  filter(fn) {
    return new Steps(this.step, [...this.map.values()].filter(fn));
  }

  label(key) {
    return this.map.get(key)?.label ?? keyLabel(key, this.step);
  }

  params(key) {
    return this.map.get(key)?.params ?? {};
  }
}

function lowerBound(arr, x) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Every hour from `start` to `end` (Dates, whole hours), without listing them. */
export class HourlySteps {
  constructor(start, end) {
    this.step = "hour";
    this.start = start;
    this.end = end;
    this.size = Math.floor((end - start) / 3600e3) + 1;
  }

  key(d) {
    return dateKey(d, "hour");
  }

  has(key) {
    if (!/T\d\d:00Z$/.test(key)) return false;
    const d = keyStart(key, "hour");
    return d >= this.start && d <= this.end;
  }

  get(key) {
    return this.has(key) ? { key } : null;
  }

  latest() {
    return this.key(this.end);
  }

  first() {
    return this.key(this.start);
  }

  neighbor(key, d) {
    if (!key) return d < 0 ? this.latest() : null;
    const t = +keyStart(key, "hour");
    const h = 3600e3;
    let n = d > 0 ? Math.floor(t / h) * h + h : Math.ceil(t / h) * h - h;
    if (d < 0 && n > +this.end) n = +this.end;
    return n >= +this.start && n <= +this.end ? this.key(new Date(n)) : null;
  }

  between(a, b, every = 1) {
    const out = [];
    const t0 = Math.max(+keyStart(a, "hour"), +this.start);
    const t1 = Math.min(+keyStart(b, "hour"), +this.end);
    for (let t = t0; t <= t1 && out.length < 100000; t += every * 3600e3) out.push(this.key(new Date(t)));
    return out;
  }

  hasDay(day) {
    const d = new Date(`${day}T00:00:00Z`);
    return d <= this.end && +d + 86400e3 > +this.start;
  }

  hasMonth(month) {
    const d = keyStart(month, "month");
    return d <= this.end && +keyEnd(month, "month") > +this.start;
  }

  inDay(day) {
    return this.between(`${day}T00:00Z`, `${day}T23:00Z`);
  }

  filter() {
    return this;
  }

  label(key) {
    return keyLabel(key, "hour");
  }

  params() {
    return {};
  }
}
// #endregion steps

/** The timesteps that pass the user's filters ({id: value}), e.g. max cloud cover. */
export function applyFilters(steps, time, filt) {
  const active = (time.filters ?? []).filter((f) => f.type === "max" && filt?.[f.id] != null && filt[f.id] < f.max);
  if (!active.length) return steps;
  return steps.filter((e) => !e.items || e.items.some((p) => active.every((f) => !(p[f.property] > filt[f.id]))));
}

// --------------------------------------------------------------------------
// Availability over an area
// --------------------------------------------------------------------------

const cache = new Map(); // key -> Promise<Steps>
const CACHE_MAX = 200;

/**
 * The timesteps of a product with data over `bbox` ([w, s, e, n], degrees):
 * a Promise of Steps / HourlySteps. Cached; boxes are rounded outward a little
 * so that small pans reuse the last answer.
 */
// #region availability
export function availability(catalog, product, bbox) {
  const time = product.time;
  const a = time.availability;
  const box = roundBox(bbox);
  let key;
  if (a.type === "list" || a.type === "hourly") key = `${product.id}|${a.type}`;
  else if (a.type === "planet") key = `planet|${a.prefix}|${credential("planet").slice(-6)}`;
  else if (a.type === "stac") key = `stac|${product.dataset}/${a.source}|${time.step}|${box}`;
  else key = `${a.type}|${a.concept_id}|${time.step}|${box}`;
  if (!cache.has(key)) {
    if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value);
    const p = PROVIDERS[a.type](catalog, product, a, box).catch((err) => {
      cache.delete(key); // retry next time
      throw err;
    });
    cache.set(key, p);
  }
  return cache.get(key);
}
// #endregion availability

function roundBox([w, s, e, n]) {
  const q = Math.max(e - w, n - s) / 8 || 0.01;
  const step = 10 ** Math.floor(Math.log10(q));
  const r = (v, f) => +(f(v / step) * step).toFixed(6);
  return [r(Math.max(-180, w), Math.floor), r(Math.max(-85, s), Math.floor), r(Math.min(180, e), Math.ceil), r(Math.min(85, n), Math.ceil)];
}

async function getJSON(url, init, what) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = (await res.text().catch(() => "")).slice(0, 200);
    throw new Error(`${what}: HTTP ${res.status}${text ? ` ${text}` : ""}`);
  }
  return res.json();
}

const PROVIDERS = {
  // #region avail-list
  async list(catalog, product, a) {
    const entries = a.values.map((key) => ({ key, label: a.labels?.[key], params: a.params?.[key] }));
    return new Steps(product.time.step, entries);
  },
  // #endregion avail-list

  async hourly(catalog, product, a) {
    const now = Date.now() - a.lag_days * 86400e3;
    return new HourlySteps(new Date(`${a.start}T00:00:00Z`), new Date(Math.floor(now / 3600e3) * 3600e3));
  },

  // #region avail-stac
  /** STAC items over the box (newest first), grouped by timestep. */
  async stac(catalog, product, a, box) {
    const src = catalog.sources[`${product.dataset}/${a.source}`];
    const props = (product.time.filters ?? []).map((f) => f.property);
    const body = {
      collections: [src.collection],
      bbox: box,
      limit: 1000,
      sortby: [{ field: "datetime", direction: "desc" }],
      fields: { include: ["id", "properties.datetime", ...props.map((p) => `properties.${p}`)], exclude: ["assets", "links", "geometry"] },
    };
    if (src.query?.length) {
      body["filter-lang"] = "cql2-json";
      body.filter = src.query.length === 1 ? src.query[0] : { op: "and", args: src.query };
    }
    const step = product.time.step;
    const groups = new Map();
    let url = `${src.stac}/search`;
    let init = { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
    let n = 0;
    while (url && n < a.max_items) {
      const page = await getJSON(url, init, "STAC search");
      for (const f of page.features) {
        const k = isoKey(f.properties.datetime, step);
        if (!groups.has(k)) groups.set(k, { key: k, items: [] });
        groups.get(k).items.push(f.properties);
      }
      n += page.features.length;
      const next = page.features.length ? page.links?.find((l) => l.rel === "next") : null;
      url = next?.href;
      init = next?.method === "POST" ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(next.merge ? { ...body, ...next.body } : next.body) } : undefined;
    }
    return new Steps(step, [...groups.values()]);
  },
  // #endregion avail-stac

  // #region avail-cmr
  /** CMR granules over the box, grouped by timestep. */
  async cmr(catalog, product, a, box) {
    const step = product.time.step;
    const groups = new Map();
    let searchAfter = null;
    let n = 0;
    while (n < a.max_items) {
      const p = new URLSearchParams({
        collection_concept_id: a.concept_id,
        bounding_box: box.join(","),
        page_size: "2000",
        sort_key: "-start_date",
      });
      const res = await fetch(`https://cmr.earthdata.nasa.gov/search/granules.json?${p}`, {
        headers: searchAfter ? { "CMR-Search-After": searchAfter } : {},
      });
      if (!res.ok) throw new Error(`CMR search: HTTP ${res.status}`);
      const entries = (await res.json()).feed.entry;
      for (const g of entries) {
        const k = isoKey(g.time_start, step);
        if (!groups.has(k)) groups.set(k, { key: k, items: [] });
        groups.get(k).items.push({ granule: g.title, start: g.time_start });
      }
      n += entries.length;
      searchAfter = res.headers.get("CMR-Search-After");
      if (!searchAfter || entries.length < 2000) break;
    }
    return new Steps(step, [...groups.values()]);
  },
  // #endregion avail-cmr

  // #region avail-planet
  /** Monthly basemaps the user's Planet key can read. */
  async planet(catalog, product, a) {
    const key = credential("planet");
    if (!key) throw new Error("no Planet API key");
    const re = new RegExp(`^${a.prefix}(\\d{4})_(\\d{2})${a.suffix}$`);
    const entries = [];
    let url = `https://api.planet.com/basemaps/v1/mosaics?${new URLSearchParams({ api_key: key, name__contains: a.prefix, _page_size: "250" })}`;
    for (let page = 0; url && page < 20; page++) {
      let data;
      try {
        data = await getJSON(url, undefined, "Planet Basemaps API");
      } catch (err) {
        throw new Error(/HTTP 40[13]/.test(err.message) ? "Planet rejected the API key (check it under Credentials)" : err.message);
      }
      for (const m of data.mosaics ?? []) {
        const match = re.exec(m.name);
        if (match) entries.push({ key: `${match[1]}-${match[2]}`, params: { mosaic: m.name } });
      }
      url = data._links?._next;
    }
    return new Steps("month", entries);
  },
  // #endregion avail-planet
};
