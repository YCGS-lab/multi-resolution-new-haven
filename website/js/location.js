// The selected place: where the maps go back to (⤢ and the 0 key), set from
// the header's search box (a starred place, or one found by the Places API,
// terraform/places), and what the location-specific tools are tied to.
//
// Place: {name, bbox?: [w, s, e, n], point?: [lon, lat], id?: starred id}.
// A starred place has an id and a bbox; a searched one has a point (a marker
// on the maps) and usually a bbox. null: no place (the maps go back to the
// catalog's extent, Greater New Haven).
//
// Search requests are light on the Places API (billed per request): a debounce,
// a minimum query length, one request in flight (the previous one aborted), a
// minimum interval between requests and a cache of answers for the page session.

import { env } from "./env.js";

// #region starred
/** Places offered before anything is typed. "bbox: null" = the catalog's extent. */
export const STARRED = [
  { id: "new-haven", name: "Greater New Haven, CT", bbox: null },
  { id: "donnelly", name: "Donnelly, Idaho", bbox: [-116.13, 44.7, -116.04, 44.76] },
];
// #endregion starred

// #region tools
/** Location-specific tools: a tab panel (main.js) and the starred place it is made for. */
export const TOOLS = [{ id: "icesat2", label: "ICESat-2 photon profiles", place: "new-haven" }];
// #endregion tools

const DEBOUNCE_MS = 300;
const MIN_INTERVAL_MS = 500; // at most ~2 requests/s
const MIN_CHARS = 3;
const MAX_SUGGESTIONS = 5;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
const round = (v) => +v.toFixed(5);

// #region place-state
export class Place {
  constructor(catalog) {
    this.catalog = catalog;
    this.listeners = new Set();
    this.current = this.starred("new-haven");
  }

  /** A starred place, with its bbox filled in. */
  starred(id) {
    const s = STARRED.find((p) => p.id === id);
    return s ? { ...s, bbox: s.bbox ?? this.catalog.lngLatExtent } : null;
  }

  onChange(fn) {
    this.listeners.add(fn);
  }

  set(place) {
    this.current = place;
    for (const fn of this.listeners) fn(place);
  }

  /** URL form: "<starred id>", "none", or "<name>|<w,s,e,n or empty>|<lon,lat or empty>". */
  encode() {
    const p = this.current;
    if (!p) return "none";
    if (p.id) return p.id;
    return [p.name, p.bbox?.map(round).join(",") ?? "", p.point?.map(round).join(",") ?? ""].join("|");
  }

  decode(s) {
    if (!s) return this.current;
    if (s === "none") return null;
    if (!s.includes("|")) return this.starred(s) ?? this.current;
    const [name, bbox, point] = s.split("|");
    const nums = (v, n) => {
      const a = v ? v.split(",").map(Number) : [];
      return a.length === n && a.every(Number.isFinite) ? a : null;
    };
    const p = { name, bbox: nums(bbox, 4), point: nums(point, 2) };
    return p.bbox || p.point ? p : this.current;
  }

  /** Center [lon, lat] of a place. */
  static center(p) {
    return p.point ?? [(p.bbox[0] + p.bbox[2]) / 2, (p.bbox[1] + p.bbox[3]) / 2];
  }

  /** Whether a place lies in the starred place `id` (its center inside that place's box). */
  within(p, id) {
    if (!p) return false;
    if (p.id === id) return true;
    const s = this.starred(id);
    const [x, y] = Place.center(p);
    return !!s && x >= s.bbox[0] && x <= s.bbox[2] && y >= s.bbox[1] && y <= s.bbox[3];
  }
}
// #endregion place-state

// #region places-api
/** The Places API (terraform/places): autocomplete, place details, geocoding. */
class PlacesApi {
  constructor(base) {
    this.base = base;
    this.cache = new Map(); // "<path>?<query>" -> answer
    this.abort = null;
    this.last = 0; // time of the last request
  }

  /** GET <base>/<path>?<params>; aborts the request in flight; throws AbortError when superseded. */
  async get(path, params) {
    const qs = new URLSearchParams(params).toString();
    const key = `${path}?${qs}`;
    if (this.cache.has(key)) return this.cache.get(key);
    this.abort?.abort();
    const abort = (this.abort = new AbortController());
    const wait = this.last + MIN_INTERVAL_MS - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    if (abort.signal.aborted) throw new DOMException("superseded", "AbortError");
    this.last = Date.now();
    const res = await fetch(`${this.base}/${path}?${qs}`, { signal: abort.signal });
    if (!res.ok) throw new Error(res.status === 429 || res.status === 503 ? "Too many searches: wait a moment" : `Search failed (${res.status})`);
    const out = await res.json();
    this.cache.set(key, out);
    return out;
  }
}
// #endregion places-api

// #region search-box
/**
 * Header search box: shows the selected place's name; typing lists matching
 * starred places, then the Places API's suggestions. `near()` is [lon, lat]
 * of the map in view (suggestions are biased towards it).
 */
export class SearchBox {
  constructor(host, place, { near } = {}) {
    this.place = place;
    this.near = near;
    this.api = env.services.places ? new PlacesApi(env.services.places.replace(/\/$/, "")) : null;
    this.items = []; // [{kind: "starred" | "suggestion", ...}]
    this.active = -1;
    this.timer = null;
    this.seq = 0; // the latest search; answers to earlier ones are dropped
    host.innerHTML = `
      <span class="ps-icon" aria-hidden="true">⌕</span>
      <input type="search" class="ps-input" autocomplete="off" spellcheck="false" role="combobox"
        aria-expanded="false" aria-controls="ps-list" aria-label="Search for a place"
        placeholder="${this.api ? "Search places…" : "Starred places"}" />
      <button type="button" class="ps-clear" title="Clear the selected place" aria-label="Clear">×</button>
      <div class="ps-list" id="ps-list" role="listbox" hidden></div>`;
    this.input = host.querySelector(".ps-input");
    this.list = host.querySelector(".ps-list");
    this.host = host;
    this.input.addEventListener("focus", () => {
      this.input.select();
      this.search(this.input.value === this.place.current?.name ? "" : this.input.value);
    });
    this.input.addEventListener("input", () => this.search(this.input.value));
    this.input.addEventListener("keydown", (e) => this.key(e));
    host.querySelector(".ps-clear").addEventListener("click", () => {
      this.place.set(null);
      this.input.value = "";
      this.input.focus();
    });
    document.addEventListener("pointerdown", (e) => !host.contains(e.target) && this.close());
    place.onChange(() => this.render());
    this.render();
  }

  /** Show the selected place's name (when not typing). */
  render() {
    if (document.activeElement !== this.input) this.input.value = this.place.current?.name ?? "";
    this.host.classList.toggle("has-place", !!this.place.current);
  }

  search(q) {
    clearTimeout(this.timer);
    const seq = ++this.seq;
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const starred = STARRED.filter((s) => words.every((w) => s.name.toLowerCase().includes(w))).map((s) => ({ kind: "starred", ...s }));
    this.show(starred, this.api && q.trim().length >= MIN_CHARS ? "Searching…" : null);
    if (!this.api || q.trim().length < MIN_CHARS) return;
    this.timer = setTimeout(async () => {
      try {
        const near = this.near?.();
        const res = await this.api.get("suggest", { q: q.trim(), ...(near ? { near: near.map(round).join(",") } : {}) });
        if (seq !== this.seq) return;
        const found = res.results.slice(0, MAX_SUGGESTIONS).map((r) => ({ kind: "suggestion", ...r }));
        this.show([...starred, ...found], found.length ? null : "No places found");
      } catch (err) {
        if (err.name !== "AbortError" && seq === this.seq) this.show(starred, err.message);
      }
    }, DEBOUNCE_MS);
  }

  show(items, note) {
    this.items = items;
    this.active = -1;
    this.list.innerHTML =
      items
        .map(
          (it, i) => `
        <button type="button" class="ps-item ${it.kind}" role="option" data-i="${i}" tabindex="-1">
          <span class="ps-mark" aria-hidden="true">${it.kind === "starred" ? "★" : "⌖"}</span>${esc(it.kind === "starred" ? it.name : it.title)}
        </button>`,
        )
        .join("") + (note ? `<div class="ps-note">${esc(note)}</div>` : "");
    this.list.hidden = !items.length && !note;
    this.input.setAttribute("aria-expanded", String(!this.list.hidden));
    this.list.querySelectorAll(".ps-item").forEach((b) => {
      b.addEventListener("pointerdown", (e) => e.preventDefault()); // keep the input focused
      b.addEventListener("click", () => this.choose(this.items[+b.dataset.i]));
    });
  }

  highlight(i) {
    this.active = i;
    this.list.querySelectorAll(".ps-item").forEach((b, j) => b.classList.toggle("active", j === i));
  }

  key(e) {
    const n = this.items.length;
    if (e.key === "ArrowDown" && n) this.highlight((this.active + 1) % n);
    else if (e.key === "ArrowUp" && n) this.highlight((this.active - 1 + n) % n);
    else if (e.key === "Enter") {
      if (this.active >= 0 || this.items.length) this.choose(this.items[Math.max(0, this.active)]);
      else if (this.input.value.trim()) this.geocode(this.input.value.trim());
    } else if (e.key === "Escape") {
      this.close();
      this.input.blur();
    } else return;
    e.preventDefault();
  }

  async choose(it) {
    if (!it) return;
    const seq = ++this.seq;
    clearTimeout(this.timer);
    if (it.kind === "starred") return this.done(this.place.starred(it.id));
    this.show([], "Finding the place…");
    try {
      const p = await this.api.get("place", { id: it.id });
      if (seq === this.seq) this.done(p);
    } catch (err) {
      if (err.name !== "AbortError" && seq === this.seq) this.show([], err.message);
    }
  }

  async geocode(q) {
    if (!this.api) return;
    const seq = ++this.seq;
    clearTimeout(this.timer);
    this.show([], "Finding the place…");
    try {
      const near = this.near?.();
      const res = await this.api.get("geocode", { q, ...(near ? { near: near.map(round).join(",") } : {}) });
      if (seq !== this.seq) return;
      if (res.point) this.done(res);
      else this.show([], `No place found for “${q}”`);
    } catch (err) {
      if (err.name !== "AbortError" && seq === this.seq) this.show([], err.message);
    }
  }

  /** {title, point, bbox} from the API, or a starred place. */
  done(p) {
    this.close();
    this.input.blur();
    this.place.set(p.id ? p : { name: p.title, point: p.point, bbox: p.bbox ?? null });
    this.render();
  }

  close() {
    clearTimeout(this.timer);
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
  }
}
// #endregion search-box

// #region tools-menu
/**
 * "Tools" drop-down: the tools for the selected place, then those of other
 * places (picking one goes there). `open(id)` shows a tool's panel; `active()`
 * is the open tool's id (or null).
 */
export class ToolsMenu {
  constructor(host, place, { open, active }) {
    this.place = place;
    this.openTool = open;
    this.activeTool = active;
    host.innerHTML = `
      <button type="button" class="pill tools-button" aria-haspopup="menu" aria-expanded="false"
        title="Tools for the selected place">Location tools <span aria-hidden="true">▾</span></button>
      <div class="tools-list" role="menu" hidden></div>`;
    this.button = host.querySelector(".tools-button");
    this.list = host.querySelector(".tools-list");
    this.button.addEventListener("click", () => (this.list.hidden ? this.show() : this.close()));
    document.addEventListener("pointerdown", (e) => !host.contains(e.target) && this.close());
    document.addEventListener("keydown", (e) => e.key === "Escape" && this.close());
  }

  /** The tools for a place (made for the starred place it lies in). */
  toolsFor(p) {
    return TOOLS.filter((t) => this.place.within(p, t.place));
  }

  show() {
    const p = this.place.current;
    const here = this.toolsFor(p);
    const other = TOOLS.filter((t) => !here.includes(t));
    const item = (t, where) => `
      <button type="button" class="tools-item${this.activeTool() === t.id ? " active" : ""}" role="menuitem" data-id="${t.id}">
        ${esc(t.label)}${where ? `<span class="tools-where">${esc(this.place.starred(t.place).name)}</span>` : ""}
      </button>`;
    const name = p ? p.name : "No place selected";
    this.list.innerHTML = `
      <div class="tools-head">${esc(name)}</div>
      ${here.length ? here.map((t) => item(t)).join("") : `<div class="tools-note">No location-specific tools ${p ? `for ${esc(p.name)} ` : ""}yet.</div>`}
      ${other.length ? `<div class="tools-head">Other places</div>${other.map((t) => item(t, true)).join("")}` : ""}`;
    this.list.querySelectorAll(".tools-item").forEach((b) =>
      b.addEventListener("click", () => {
        const t = TOOLS.find((x) => x.id === b.dataset.id);
        this.close();
        if (!here.includes(t)) this.place.set(this.place.starred(t.place));
        this.openTool(t.id);
      }),
    );
    this.list.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
  }

  close() {
    this.list.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  /** Mark the button while a tool is open. */
  render() {
    this.button.classList.toggle("active", !!this.activeTool());
  }
}
// #endregion tools-menu
