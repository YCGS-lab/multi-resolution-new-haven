// Animation tab, after NASA Worldview's: pick an image and a start and end
// date; "Load imagery" fetches and renders every frame's tiles for the area in
// view ahead of time (into the tile cache of tiles.js, with a progress bar);
// then a slider jumps between frames, and Play steps through them at a chosen
// speed, optionally looping. Frames are the timesteps with data in view
// between the two dates (after the filters, e.g. max cloud cover); for hourly
// data, every N hours.

import { Deck, MapView } from "../vendor/deck-gl-raster.js";
import { cdsArea, cdsGrids, hourKey } from "./cds.js";
import { openCredentials } from "./env.js";
import {
  CONTROLLER,
  LoadingState,
  MapChrome,
  backgroundLayer,
  clampViewState,
  fromDeckViewState,
  homeViewState,
  keyHTML,
  landmarkLayers,
  productLayers,
  showNotices,
  titleHTML,
  toDeckViewState,
  viewBounds,
} from "./mapview.js";
import { Picker } from "./picker.js";
import { Slot, slippyZoom } from "./slot.js";
import { prefetchTiles } from "./tiles.js";
import { dayOf, keyLabel, keyStart } from "./time.js";

const MAX_FRAMES = 120;
const CONCURRENCY = 6;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

export class Animation {
  constructor(root, catalog, settings) {
    this.root = root;
    this.catalog = catalog;
    this.settings = settings;
    this.active = false;
    this.frames = []; // timestep keys
    this.index = 0;
    this.shown = null; // last frame whose tiles finished loading: drawn under the current one (no flashes)
    this.playing = false;
    this.timer = null;
    this.from = null; // "YYYY-MM-DD"
    this.to = null;
    this.loaded = null; // {key of what was loaded}
    this.loadJob = 0;
    this.mapEl = root.querySelector("#anim-map");
    this.chrome = new MapChrome(root.querySelector(".anim-frame"), catalog);
    this.loading = new LoadingState(root.querySelector("#anim-map .map-message"));
    this.noticeEl = root.querySelector("#anim-map .map-notice");
    this.slot = new Slot(catalog, { onChange: () => this.slotChanged() });
    this.picker = new Picker(root.querySelector("#anim-picker"), catalog, { onSelect: (id) => this.select(id) });

    const $ = (s) => root.querySelector(s);
    this.el = {
      from: $("#anim-from"),
      to: $("#anim-to"),
      every: $("#anim-every"),
      everyLabel: $(".anim-every"),
      filters: $(".anim-filters"),
      load: $("#anim-load"),
      bar: $(".anim-progress .bar"),
      progress: $(".anim-progress"),
      progressText: $(".anim-progress-text"),
      slider: $("#anim-slider"),
      ticks: $(".anim-ticks"),
      date: $("#anim-date"),
      play: $("#anim-play"),
      prev: $("#anim-prev"),
      next: $("#anim-next"),
      speed: $("#anim-speed"),
      loop: $("#anim-loop"),
      count: $(".anim-count"),
    };
    this.el.from.addEventListener("change", () => this.setRange(this.el.from.value, this.to));
    this.el.to.addEventListener("change", () => this.setRange(this.from, this.el.to.value));
    this.el.every.addEventListener("change", () => this.computeFrames());
    this.el.load.addEventListener("click", () => this.load());
    this.el.slider.addEventListener("input", () => this.show(+this.el.slider.value));
    this.el.play.addEventListener("click", () => this.togglePlay());
    this.el.prev.addEventListener("click", () => this.stepFrame(-1));
    this.el.next.addEventListener("click", () => this.stepFrame(1));
    this.el.speed.addEventListener("change", () => this.playing && this.play());
    root.querySelector("#anim-reset").addEventListener("click", () => this.reset());
    root.querySelector("#anim-zoom-in").addEventListener("click", () => this.zoomBy(1));
    root.querySelector("#anim-zoom-out").addEventListener("click", () => this.zoomBy(-1));

    this.size = [800, 450];
    this.viewState = homeViewState(catalog.extent, ...this.size);
  }

  /** The Deck is made when the tab is first shown (its map needs a size). */
  ensureDeck() {
    if (this.deck) return;
    const c = this.catalog;
    this.size = [this.mapEl.clientWidth || 800, this.mapEl.clientHeight || 450];
    this.viewState = homeViewState(c.extent, ...this.size);
    this.deck = new Deck({
      parent: this.mapEl,
      views: new MapView({ id: "anim", controller: CONTROLLER }),
      viewState: toDeckViewState(this.viewState, c),
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(fromDeckViewState(viewState, c), c.extent, ...this.size);
        this.update();
        return toDeckViewState(this.viewState, c);
      },
      onResize: ({ width, height }) => {
        this.size = [width, height];
        this.viewState = clampViewState(this.viewState, c.extent, width, height);
        this.update();
      },
      layers: [],
    });
  }

  get state() {
    return { id: this.slot.sel.id, from: this.from, to: this.to };
  }

  restore(id, from, to) {
    this.from = from || null;
    this.to = to || null;
    this.userRange = !!(from && to);
    this.select(id, true);
  }

  setActive(on) {
    this.active = on;
    if (on) {
      this.ensureDeck();
      if (!this.slot.sel.id) {
        const def = this.catalog.get("landsat/truecolor") ? "landsat/truecolor" : this.catalog.order.find((i) => this.catalog.get(i).time);
        if (def) this.select(def);
      }
      this.update();
    } else this.pause();
  }

  select(id, keepRange = false) {
    this.pause();
    if (!keepRange) {
      this.userRange = false;
      this.from = this.to = null;
    }
    this.frames = [];
    this.loaded = null;
    this.slot.select(this.catalog.get(id) ? id : null, false);
    this.buildFilters();
  }

  /** Credentials changed. */
  refresh() {
    this.slot.refresh(0);
    this.picker.render();
    this.update();
  }

  slotChanged() {
    this.picker.set(this.slot.sel.id);
    const p = this.slot.product;
    const hourly = p?.time?.step === "hour";
    this.el.everyLabel.hidden = !hourly;
    // Default range: the latest ~20 timesteps with data in view (hourly: the last day).
    if (p?.time && this.slot.steps && !this.userRange && !this.from) {
      const keys = hourly ? null : this.slot.steps.keys;
      const last = this.slot.steps.latest();
      if (last) {
        this.to = dayOf(last);
        this.from = hourly ? this.to : dayOf(keys[Math.max(0, keys.length - 20)]);
      }
    }
    this.computeFrames();
    this.onChange?.();
  }

  setRange(from, to) {
    this.userRange = true;
    this.from = from || this.from;
    this.to = to || this.to;
    if (this.from && this.to && this.from > this.to) [this.from, this.to] = [this.to, this.from];
    this.computeFrames();
    this.onChange?.();
  }

  buildFilters() {
    const p = this.slot.product;
    const filters = p?.time?.filters ?? [];
    this.el.filters.innerHTML = filters
      .map(
        (f) => `<label class="tc-filter">${esc(f.label)}
          <input type="range" data-filter="${f.id}" min="${f.min}" max="${f.max}" step="${f.step}" value="${this.slot.sel.f[f.id] ?? f.default}" />
          <output>≤ ${this.slot.sel.f[f.id] ?? f.default}${f.unit}</output></label>`,
      )
      .join("");
    this.el.filters.querySelectorAll("input").forEach((input) => {
      const f = filters.find((x) => x.id === input.dataset.filter);
      input.addEventListener("input", () => (input.nextElementSibling.value = `≤ ${input.value}${f.unit}`));
      input.addEventListener("change", () => this.slot.setTime({ f: { [f.id]: +input.value } }));
    });
  }

  // #region anim-frames
  /** Frames: the timesteps with data in view between the dates (hourly: every N hours). */
  computeFrames() {
    const p = this.slot.product;
    const steps = this.slot.steps;
    const prevKey = this.frames[this.index];
    let frames = [];
    this.truncated = false;
    if (p?.time && steps && this.from && this.to) {
      if (p.time.step === "hour") frames = steps.between(`${this.from}T00:00Z`, `${this.to}T23:00Z`, +this.el.every.value);
      else if (p.time.step === "year") frames = steps.between(this.from.slice(0, 4), this.to.slice(0, 4));
      else if (p.time.step === "month") frames = steps.between(this.from.slice(0, 7), this.to.slice(0, 7));
      else frames = steps.between(this.from, `${this.to}￿`);
      if (frames.length > MAX_FRAMES) {
        frames = frames.slice(-MAX_FRAMES);
        this.truncated = true;
      }
    }
    this.frames = frames;
    this.index = Math.max(0, frames.indexOf(prevKey));
    if (frames.length && prevKey == null) this.index = frames.length - 1;
    this.shown = null;
    this.renderControls();
    this.update();
  }
  // #endregion anim-frames

  /** Selection key of what Load imagery would fetch (frames, filters, area). */
  loadKey() {
    const b = this.bounds?.map((v) => v.toFixed(4));
    return JSON.stringify([this.slot.sel.id, this.frames, this.slot.sel.f, b, Math.round(this.viewState.zoom * 10)]);
  }

  // #region anim-load
  /** Fetch and render every frame's tiles for the area in view, with progress. */
  async load() {
    const p = this.slot.product;
    if (!p || !this.frames.length || !this.bounds) return;
    this.pause();
    const job = ++this.loadJob;
    const key = this.loadKey();
    const progress = (done, total, text) => {
      if (job !== this.loadJob) return;
      const f = total ? done / total : 0;
      this.el.progress.hidden = false;
      this.el.bar.style.width = `${(100 * f).toFixed(1)}%`;
      this.el.progressText.textContent = text ?? `${done} / ${total} tiles (${Math.round(100 * f)}%)`;
    };
    this.busy = true;
    this.el.load.disabled = true;
    try {
      const cds = p.layers.map((l) => this.catalog.sources[l.source]).find((s) => s.type === "cds");
      if (cds) {
        // One CDS request per month for all the frames' hours.
        progress(0, 1, "Requesting from the Climate Data Store…");
        await cdsGrids(cds, cdsArea(cds, this.bounds), this.frames.map(hourKey), {
          onStatus: (s) => s && progress(0, 1, s),
        });
        progress(1, 1, `${this.frames.length} frames loaded`);
      } else {
        const zoom = toDeckViewState(this.viewState, this.catalog).zoom;
        const jobs = this.frames.flatMap((t) => prefetchTiles(this.catalog, p, this.slot.ctx(t, null), this.bounds, zoom));
        let done = 0;
        progress(0, jobs.length);
        let next = 0;
        const worker = async () => {
          while (next < jobs.length && job === this.loadJob) {
            await jobs[next++]();
            progress(++done, jobs.length);
          }
        };
        await Promise.all(Array.from({ length: CONCURRENCY }, worker));
        if (job === this.loadJob) progress(done, jobs.length, `${this.frames.length} frames loaded (${jobs.length} tiles)`);
      }
      if (job === this.loadJob) this.loaded = key;
    } catch (err) {
      progress(0, 1, `Loading failed: ${err.message}`);
      this.el.progress.classList.add("error");
    } finally {
      if (job === this.loadJob) this.busy = false;
      this.renderControls();
      this.update();
    }
  }
  // #endregion anim-load

  // #region anim-play
  togglePlay() {
    this.playing ? this.pause() : this.play();
  }

  play() {
    if (this.frames.length < 2) return;
    clearInterval(this.timer);
    this.playing = true;
    const fps = +this.el.speed.value;
    if (this.index >= this.frames.length - 1 && !this.el.loop.checked) this.show(0);
    this.timer = setInterval(() => {
      if (this.index >= this.frames.length - 1) {
        if (this.el.loop.checked) this.show(0);
        else this.pause();
      } else this.show(this.index + 1);
    }, 1000 / fps);
    this.renderControls();
  }

  pause() {
    clearInterval(this.timer);
    this.timer = null;
    this.playing = false;
    this.renderControls();
  }

  stepFrame(d) {
    if (!this.frames.length) return;
    this.pause();
    const n = this.frames.length;
    this.show(this.el.loop.checked ? (this.index + d + n) % n : Math.max(0, Math.min(n - 1, this.index + d)));
  }

  show(i) {
    if (i === this.index) return;
    this.index = i;
    this.renderControls();
    this.update();
  }
  // #endregion anim-play

  zoomBy(d) {
    this.viewState = clampViewState({ ...this.viewState, zoom: this.viewState.zoom + d }, this.catalog.extent, ...this.size);
    this.update();
  }

  reset() {
    this.viewState = homeViewState(this.catalog.extent, ...this.size);
    this.update();
  }

  renderControls() {
    const p = this.slot.product;
    const step = p?.time?.step;
    const n = this.frames.length;
    const el = this.el;
    el.from.value = this.from ?? "";
    el.to.value = this.to ?? "";
    const steps = this.slot.steps;
    if (steps?.first?.()) el.from.min = el.to.min = dayOf(keyStart(steps.first(), step).toISOString());
    if (steps?.latest?.()) el.from.max = el.to.max = dayOf(keyStart(steps.latest(), step).toISOString());
    el.slider.max = String(Math.max(0, n - 1));
    el.slider.value = String(this.index);
    el.slider.disabled = n < 2;
    el.play.disabled = el.prev.disabled = el.next.disabled = n < 2;
    el.play.innerHTML = this.playing ? "&#10074;&#10074;" : "&#9654;";
    el.play.title = this.playing ? "Pause (space)" : "Play (space)";
    el.play.setAttribute("aria-pressed", String(this.playing));
    const t = this.frames[this.index];
    el.date.textContent = t ? (steps?.label(t) ?? keyLabel(t, step)) : "—";
    el.count.textContent = !p?.time
      ? "This image has no time dimension"
      : this.slot.loadingSteps
        ? "Finding imagery…"
        : `${n} frame${n === 1 ? "" : "s"}${this.truncated ? ` (the last ${MAX_FRAMES})` : ""}`;
    el.load.disabled = !n || this.busy;
    const stale = this.loaded && this.loaded !== this.loadKey();
    el.load.textContent = this.loaded && !stale ? "Reload imagery" : "Load imagery";
    el.load.classList.toggle("primary", !this.loaded || stale);
    const tickKey = this.frames.join();
    if (el.ticks.dataset.key !== tickKey) {
      el.ticks.dataset.key = tickKey;
      el.ticks.innerHTML = this.frames
        .map((k, i) => `<span style="left:${n > 1 ? (100 * i) / (n - 1) : 50}%" title="${esc(steps?.label(k) ?? k)}"></span>`)
        .join("");
    }
  }

  update() {
    if (this.pending || !this.deck) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.render();
    });
  }

  render() {
    if (!this.active || !this.deck) return;
    const c = this.catalog;
    const [w, h] = this.size;
    this.bounds = viewBounds(this.viewState, c, w, h);
    this.slot.setView(this.bounds, slippyZoom(this.viewState.zoom));
    const p = this.slot.product;
    const status = this.slot.status();
    const layers = [backgroundLayer("anim-bg", c)];
    const t = this.frames[this.index];
    if (p && !status) {
      const extra = (k) => ({ time: this.slot.ctx(k, null), view: this.bounds, onReady: () => this.update() });
      // The last fully drawn frame stays underneath until the current one has loaded (no flashes).
      const prev = this.shown;
      if (prev && prev !== t) layers.push(...productLayers("anim-prev", c, p, null, undefined, extra(prev)));
      if (t) {
        const cur = productLayers("anim-cur", c, p, this.loading, undefined, extra(t));
        layers.push(...cur.map((l) => (l.clone ? l.clone({ onViewportLoad: () => this.frameLoaded(t) }) : l)));
      } else if (!p.time) layers.push(...productLayers("anim-cur", c, p, this.loading));
    }
    if (this.settings.labels) layers.push(...landmarkLayers("anim-landmarks", c, p?.landmark_color));
    this.deck.setProps({ viewState: toDeckViewState(this.viewState, c), layers });
    this.chrome.update(this.viewState, w, h, this.settings.labels);
    showNotices(
      this.noticeEl,
      [{ tag: "", status: status ?? (p?.time && this.slot.steps && !this.frames.length ? { kind: "empty", message: "No frames: no imagery in view between these dates." } : null) }],
      (name) => openCredentials(name),
    );
    const label = t ? (this.slot.steps?.label(t) ?? keyLabel(t, p.time.step)) : "";
    const key = JSON.stringify([p?.id, label]);
    if (key !== this.titleKey) {
      this.titleKey = key;
      this.root.querySelector(".anim-title").innerHTML = p ? `<div class="title-block">${titleHTML(p, { time: label, t })}</div>` : "";
      this.root.querySelector(".anim-legend").innerHTML = p ? `<div class="key-block">${keyHTML(p, c)}</div>` : "";
    }
    this.renderControls();
  }

  frameLoaded(t) {
    if (this.frames[this.index] === t && this.shown !== t) {
      this.shown = t;
      this.update();
    }
  }
}
