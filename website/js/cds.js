// Copernicus Climate Data Store (CDS) requests from the browser, with the
// user's API key: submit a request for some hours over an area, wait for the
// job in the CDS queue, download the GRIB result and decode it (grib.js).
//
// API (cds.climate.copernicus.eu/api): POST retrieve/v1/processes/<dataset>/execution
// -> job; GET retrieve/v1/jobs/<id> until "successful"; GET .../results -> the
// file's URL. Header PRIVATE-TOKEN: <key>.

import { credential } from "./env.js";
import { decodeGrib } from "./grib.js";
import { keyStart } from "./time.js";

const POLL_MS = 2000;
const grids = new Map(); // `${dataset}|${variable}|${area}|${hourKey}` -> grid message
const pending = new Map(); // request key -> Promise

// #region cds-area
/**
 * The request area for a view (lon / lat box): the view grown to at least
 * 4 degrees and snapped to whole degrees, capped at max_area_deg a side, so
 * small pans reuse earlier requests. [north, west, south, east] as the CDS wants.
 */
export function cdsArea(spec, [w, s, e, n]) {
  const grow = (lo, hi, min) => {
    const c = (lo + hi) / 2;
    const half = Math.min(spec.max_area_deg, Math.max(min, hi - lo)) / 2;
    return [Math.floor(c - half), Math.ceil(c + half)];
  };
  const [w2, e2] = grow(w, e, 4);
  const [s2, n2] = grow(s, n, 4);
  return [Math.min(90, n2), Math.max(-180, w2), Math.max(-90, s2), Math.min(180, e2)];
}
// #endregion cds-area

/** A decoded grid already downloaded for an hour; null: the CDS had no data; undefined: not downloaded. */
export function cachedGrid(spec, area, hourKey) {
  const k = `${spec.dataset}|${spec.variable}|${area}|${hourKey}`;
  return grids.has(k) ? grids.get(k) : undefined;
}

// #region cds-fetch
/**
 * Grids for the given hours ("YYYY-MM-DDTHH:00Z") over `area`: Map hourKey ->
 * {ni, nj, west, north, di, dj, values}. One CDS request per calendar month
 * (days x hours of that month). `onStatus(text)` hears about queue progress.
 */
export async function cdsGrids(spec, area, hourKeys, { onStatus, signal } = {}) {
  const key = credential("cds");
  if (!key) throw new Error("no CDS API key");
  const todo = hourKeys.filter((h) => cachedGrid(spec, area, h) === undefined);
  const byMonth = new Map();
  for (const h of todo) {
    const m = h.slice(0, 7);
    if (!byMonth.has(m)) byMonth.set(m, []);
    byMonth.get(m).push(h);
  }
  await Promise.all(
    [...byMonth.values()].map((hours) => {
      const rk = `${spec.dataset}|${spec.variable}|${area}|${hours.join()}`;
      if (!pending.has(rk)) {
        pending.set(
          rk,
          request(spec, area, hours, key, onStatus, signal).finally(() => pending.delete(rk)),
        );
      }
      return pending.get(rk);
    }),
  );
  return new Map(hourKeys.map((h) => [h, cachedGrid(spec, area, h)]));
}

async function request(spec, area, hours, key, onStatus, signal) {
  const days = [...new Set(hours.map((h) => h.slice(8, 10)))].sort();
  const times = [...new Set(hours.map((h) => h.slice(11, 16)))].sort();
  const headers = { "PRIVATE-TOKEN": key, "content-type": "application/json" };
  const inputs = {
    variable: [spec.variable],
    year: [hours[0].slice(0, 4)],
    month: [hours[0].slice(5, 7)],
    day: days,
    time: times,
    area,
    data_format: "grib",
    download_format: "unarchived",
  };
  onStatus?.("Sending the request to the Climate Data Store…");
  let job = await call(`${spec.api}/retrieve/v1/processes/${spec.dataset}/execution`, {
    method: "POST",
    headers,
    body: JSON.stringify({ inputs }),
    signal,
  });
  const id = job.jobID;
  const t0 = Date.now();
  while (!["successful", "failed", "rejected", "dismissed", "deleted"].includes(job.status)) {
    onStatus?.(`Climate Data Store: request ${job.status} (${Math.round((Date.now() - t0) / 1000)} s)…`);
    await sleep(POLL_MS, signal);
    job = await call(`${spec.api}/retrieve/v1/jobs/${id}`, { headers, signal });
  }
  if (job.status !== "successful") {
    let detail = "";
    try {
      const r = await call(`${spec.api}/retrieve/v1/jobs/${id}/results`, { headers, signal });
      detail = r.detail || r.title || "";
    } catch (err) {
      detail = err.message;
    }
    throw new Error(`CDS request ${job.status}${detail ? `: ${detail}` : ""}`);
  }
  const results = await call(`${spec.api}/retrieve/v1/jobs/${id}/results`, { headers, signal });
  const href = results.asset?.value?.href;
  if (!href) throw new Error("CDS: no result file");
  onStatus?.("Downloading from the Climate Data Store…");
  const res = await fetch(href, { signal });
  if (!res.ok) throw new Error(`CDS download: HTTP ${res.status}`);
  const msgs = decodeGrib(await res.arrayBuffer());
  for (const m of msgs) {
    const hk = `${m.time.toISOString().slice(0, 13)}:00Z`;
    if (spec.offset) for (let i = 0; i < m.values.length; i++) m.values[i] += spec.offset;
    grids.set(`${spec.dataset}|${spec.variable}|${area}|${hk}`, m);
  }
  // Hours the CDS returned nothing for (e.g. beyond the latest data): remember as empty.
  for (const h of hours) {
    const k = `${spec.dataset}|${spec.variable}|${area}|${h}`;
    if (!grids.has(k)) grids.set(k, null);
  }
  onStatus?.("");
}
// #endregion cds-fetch

async function call(url, init) {
  const res = await fetch(url, init);
  let body = null;
  try {
    body = await res.json();
  } catch {
    // not JSON
  }
  if (!res.ok) {
    const msg = body?.detail || body?.title || body?.message || `HTTP ${res.status}`;
    if (res.status === 401) throw new Error("the CDS rejected the API key (check it under Credentials)");
    if (res.status === 403) throw new Error(`${msg} (accept the dataset's licence on the CDS website)`);
    throw new Error(`CDS: ${msg}`);
  }
  return body;
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

/** Hour keys (as cdsGrids wants) of a time context: its hour. */
export const hourKey = (t) => `${keyStart(t, "hour").toISOString().slice(0, 13)}:00Z`;
