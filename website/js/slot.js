// One map's selection: a product and its time (timestep, optional end of a
// window, options, filters), plus what is known about the area in view: the
// timesteps with data there, and whether the product can be shown at all
// (credentials, cloud, coverage, zoom). Used by every map: viewer A and B,
// grid slots, the animation.
//
// Selection: {id, t, t2, o: {option: value}, f: {filter: value}, auto}
//   t:    timestep key, or null with auto = true: the latest with data in view
//   t2:   end of a window (key), or null
// URL form (encodeSel / decodeSel): "<id>@<t>..<t2>;px=median;cc=30"

import { requirement } from "./env.js";
import { applyFilters, availability, daysBetween, dayOf, interval, keyLabel } from "./time.js";

const C = 2 * Math.PI * 6378137;
/** Slippy-map zoom (256 px tiles) of a world zoom (2^zoom px per Web Mercator meter). */
export const slippyZoom = (worldZoom) => worldZoom + Math.log2(C / 256);

// #region selection
export function newSel(catalog, id) {
  const p = catalog.get(id);
  return { id: p ? id : null, t: null, t2: null, o: defaultOptions(p), f: defaultFilters(p), auto: true };
}

export function defaultOptions(p) {
  return Object.fromEntries((p?.time?.window?.options ?? []).map((o) => [o.id, o.default]));
}

export function defaultFilters(p) {
  return Object.fromEntries((p?.time?.filters ?? []).map((f) => [f.id, f.default]));
}

/** "<id>@<t>..<t2>;opt=value;filter=value" (only what differs from the defaults). */
export function encodeSel(catalog, s) {
  if (!s?.id) return "";
  const p = catalog.get(s.id);
  let out = s.id;
  if (!s.auto && s.t) out += `@${s.t}${s.t2 ? `..${s.t2}` : ""}`;
  const extra = [];
  const o = defaultOptions(p);
  const f = defaultFilters(p);
  for (const [k, v] of Object.entries(s.o ?? {})) if (v !== o[k]) extra.push(`${k}=${v}`);
  for (const [k, v] of Object.entries(s.f ?? {})) if (v !== f[k]) extra.push(`${k}=${v}`);
  return extra.length ? `${out};${extra.join(";")}` : out;
}

export function decodeSel(catalog, str) {
  if (!str) return newSel(catalog, null);
  const [head, ...extra] = str.split(";");
  const [id, time] = head.split("@");
  const s = newSel(catalog, id);
  if (!s.id) return s;
  const p = catalog.get(s.id);
  // (an "@<view>" suffix from older links is not a time)
  if (time && /^\d{4}/.test(time) && p.time) {
    const [t, t2] = time.split("..");
    Object.assign(s, { t, t2: p.time.window ? t2 || null : null, auto: false });
  }
  for (const kv of extra) {
    const [k, v] = kv.split("=");
    if (k in s.o) s.o[k] = v;
    else if (k in s.f) s.f[k] = Number(v);
  }
  return s;
}
// #endregion selection

// #region slot
export class Slot {
  /** onChange(): the selection, timesteps or status changed (re-render). */
  constructor(catalog, { onChange } = {}) {
    this.catalog = catalog;
    this.onChange = onChange;
    this.sel = newSel(catalog, null);
    this.bbox = null; // lon / lat of the view
    this.zoom = null; // slippy zoom of the view
    this.raw = null; // Steps over the view (unfiltered)
    this.steps = null; // ... after the filters
    this.loadingSteps = false;
    this.stepsError = null;
    this.timer = null;
    this.request = 0;
  }

  get product() {
    return this.catalog.get(this.sel.id);
  }

  get time() {
    return this.product?.time ?? null;
  }

  /**
   * Select a product. Within a dataset (same time spec), the time selection is
   * kept, so switching e.g. true color -> false color keeps the date.
   */
  select(id, keepTime = true) {
    const prev = this.product;
    const p = this.catalog.get(id);
    const same = keepTime && prev && p && prev.dataset === p.dataset && JSON.stringify(prev.time) === JSON.stringify(p.time);
    this.sel = same ? { ...this.sel, id: p.id } : newSel(this.catalog, id);
    if (!same) {
      this.raw = this.steps = null;
      this.stepsError = null;
    }
    this.refresh(0);
    this.onChange?.();
  }

  setSel(sel) {
    const prev = this.product;
    this.sel = { ...sel };
    if (!prev || prev.dataset !== this.product?.dataset) this.raw = this.steps = null;
    this.refresh(0);
    this.onChange?.();
  }

  /** Change the time selection: {t, t2, o, f} (any of them); a t turns auto off. */
  setTime(patch) {
    const s = { ...this.sel, ...patch };
    if ("t" in patch) s.auto = patch.t == null;
    if (patch.o) s.o = { ...this.sel.o, ...patch.o };
    if (patch.f) s.f = { ...this.sel.f, ...patch.f };
    if (s.t2 && s.t && s.t2 < s.t) s.t2 = null;
    this.sel = s;
    if (patch.f && this.raw) this.steps = applyFilters(this.raw, this.time, this.sel.f);
    this.resolve();
    this.onChange?.();
  }

  /** Step to the previous / next timestep with data in view. */
  step(d) {
    if (!this.steps) return;
    const k = this.steps.neighbor(this.sel.t, d);
    if (k) this.setTime({ t: k, t2: this.sel.t2 ? shiftWindow(this.sel, k, this.time.step) : null });
  }

  /** The view changed: [w, s, e, n] degrees, slippy zoom. Timesteps are re-listed after a pause. */
  setView(bbox, zoom) {
    const moved = !this.bbox || bbox.some((v, i) => Math.abs(v - this.bbox[i]) > 1e-9);
    this.bbox = bbox;
    this.zoom = zoom;
    if (moved) this.refresh(400);
  }

  refresh(delay) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), delay);
  }

  /** List the timesteps over the view (if the product can be shown here). */
  async load() {
    const p = this.product;
    if (!p?.time || !this.bbox || this.blocker()) return;
    const req = ++this.request;
    this.loadingSteps = true;
    this.stepsError = null;
    this.onChange?.();
    try {
      const raw = await availability(this.catalog, p, this.bbox);
      if (req !== this.request || this.product !== p) return;
      this.raw = raw;
      this.steps = applyFilters(raw, p.time, this.sel.f);
    } catch (err) {
      if (req !== this.request) return;
      console.warn(`${p.id}: could not list timesteps`, err);
      this.stepsError = err.message;
    }
    this.loadingSteps = false;
    this.resolve();
    this.onChange?.();
  }

  /** In auto mode, follow the latest timestep. */
  resolve() {
    if (this.sel.auto && this.steps) {
      const t = this.steps.latest();
      if (t !== this.sel.t) this.sel = { ...this.sel, t, t2: null };
    }
  }

  // #region slot-blocker
  /** Why the product cannot be drawn here, before any timestep question (or null). */
  blocker() {
    const p = this.product;
    if (!p) return null;
    const req = requirement(p);
    if (!req.ok) return { kind: req.kind, credential: req.credential, message: req.message };
    const cov = p.coverage;
    if (cov && this.bbox) {
      const [w, s, e, n] = this.bbox;
      const [cw, cs, ce, cn] = cov.bbox;
      if (e < cw || w > ce || n < cs || s > cn) return { kind: "outside", message: `Dataset unavailable here: it covers ${cov.name}.` };
    }
    if (p.min_zoom != null && this.zoom != null && this.zoom < p.min_zoom - 0.5)
      return { kind: "zoom", message: "Zoom in to view this dataset (too much data at this scale)." };
    return null;
  }
  // #endregion slot-blocker

  /**
   * What the map should say instead of (or while) drawing:
   * {kind, message} or null when the image can be drawn.
   */
  status() {
    const p = this.product;
    if (!p) return null;
    const b = this.blocker();
    if (b) return b;
    if (!p.time) return null;
    if (this.stepsError) return { kind: "error", message: `Could not list the available dates: ${this.stepsError}` };
    if (!this.steps) return { kind: "loading", message: "Finding imagery for this area…" };
    if (!this.sel.t)
      return {
        kind: "empty",
        message: this.raw?.size ? "No imagery in view passes the filters." : "Timestep not available: no imagery for this area.",
      };
    if (!this.sel.t2 && !this.steps.has(this.sel.t) && this.time.availability.type !== "list")
      return { kind: "missing", message: `Timestep not available here: no imagery for ${keyLabel(this.sel.t, this.time.step)} in view.` };
    return null;
  }

  /** The time context the layers need (for the selection, or another timestep), or null. */
  ctx(t = this.sel.t, t2 = t === this.sel.t ? this.sel.t2 : null) {
    const p = this.product;
    if (!p?.time) return null;
    const { o, f } = this.sel;
    if (!t) return null;
    const step = p.time.step;
    const params = this.steps?.params?.(t) ?? {};
    const [start, end] = interval(t, t2, step);
    return {
      t,
      t2,
      step,
      start,
      end,
      params,
      options: o,
      filters: f,
      key: [t, t2 ?? "", ...Object.values(o), ...Object.values(f)].join("|"),
    };
  }

  /** Short text for titles: "18 Sep 2026" / "1 Jun 2026 to 31 Aug 2026 (median)". */
  timeLabel() {
    const p = this.product;
    const { t, t2, o } = this.sel;
    if (!p?.time || !t) return "";
    const step = p.time.step;
    const lab = (k) => this.steps?.label?.(k) ?? keyLabel(k, step);
    if (!t2) return lab(t);
    const px = p.time.window?.options?.find((x) => x.id === "px");
    const how = px ? px.choices.find((c) => c.value === o.px)?.label.toLowerCase() : "";
    return `${keyLabel(t, step)} to ${keyLabel(t2, step)}${how ? ` (${how} pixel)` : ""}`;
  }
}
// #endregion slot

/** A window moved to start at `t`, keeping its length. */
function shiftWindow(sel, t, step) {
  if (!sel.t2 || !sel.t || step !== "day") return null;
  const d = new Date(`${dayOf(t)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + daysBetween(sel.t, sel.t2, step));
  return d.toISOString().slice(0, 10);
}
