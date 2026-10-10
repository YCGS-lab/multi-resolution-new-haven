// Grid of images with synchronized pan / zoom.
//
// All slots share ONE deck.gl canvas (fixed behind the page) with one
// OrthographicView per slot, placed over the slot's map area; the slot's own
// HTML (picker, title, axes, key) sits on top, and the map area is a
// transparent hole that lets pointer events through to deck.gl. This keeps a
// single WebGL context however many slots there are.

import { Deck, MapView } from "../vendor/deck-gl-raster.js";
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
  titleHTML,
  toDeckViewState,
} from "./mapview.js";
import { Picker } from "./picker.js";

let nextUid = 0;

export class Grid {
  constructor(root, catalog, settings) {
    this.root = root;
    this.catalog = catalog;
    this.settings = settings;
    this.container = root.querySelector(".grid-slots");
    this.deckEl = document.getElementById("grid-deck");
    this.cols = 2;
    this.slots = [];
    this.addRows(2);
    this.rearrange = false;
    this.viewState = null;
    this.slotSize = null;
    this.active = false;

    root.querySelector("#grid-cols").addEventListener("change", (e) => this.setCols(+e.target.value));
    root.querySelector("#add-row").addEventListener("click", () => {
      this.addRows(1);
      this.renderSlots();
      this.slots.at(-this.cols).el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    root.querySelector("#remove-row").addEventListener("click", () => this.removeEmptyRow());
    root.querySelector("#rearrange-toggle").addEventListener("change", (e) => this.setRearrange(e.target.checked));
    root.querySelector("#grid-reset").addEventListener("click", () => this.reset());

    // #region grid-deck
    this.deck = new Deck({
      parent: this.deckEl,
      views: [],
      viewState: {},
      layers: [],
      layerFilter: ({ layer, viewport }) => layer.id.startsWith(`${viewport.id}-`),
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(fromDeckViewState(viewState, catalog), catalog.extent, ...this.slotSize);
        this.update();
        return toDeckViewState(this.viewState, catalog);
      },
    });
    // #endregion grid-deck

    window.addEventListener("scroll", () => this.active && this.layout(), { passive: true });
    window.addEventListener("resize", () => this.active && this.layout());
    new ResizeObserver(() => this.active && this.layout()).observe(this.container);
    this.renderSlots();
  }

  // ----- state ---------------------------------------------------------

  get state() {
    return { cols: this.cols, slots: this.slots.map((s) => s.sel) };
  }

  restore({ cols, slots }) {
    this.cols = cols;
    this.root.querySelector("#grid-cols").value = String(cols);
    this.slots = [];
    for (const sel of slots) {
      const slot = this.newSlot();
      this.slots.push(slot);
      if (sel) this.select(slot, sel, false);
    }
    this.pad();
    this.renderSlots();
  }

  setActive(on) {
    this.active = on;
    this.deckEl.hidden = !on;
    if (on) this.layout();
  }

  newSlot() {
    return { uid: `s${nextUid++}`, sel: null }; // sel: product id
  }

  addRows(n) {
    for (let i = 0; i < n * this.cols; i++) this.slots.push(this.newSlot());
  }

  /** Fill the last row with empty slots. */
  pad() {
    while (this.slots.length % this.cols || !this.slots.length) this.slots.push(this.newSlot());
  }

  setCols(n) {
    this.cols = n;
    // Drop trailing empty slots beyond a full row, then pad.
    while (this.slots.length > n && !this.slots.at(-1).sel) this.slots.pop();
    this.pad();
    this.renderSlots();
  }

  removeEmptyRow() {
    const last = this.slots.slice(-this.cols);
    if (this.slots.length > this.cols && last.every((s) => !s.sel)) {
      this.slots.splice(-this.cols);
      this.renderSlots();
    }
  }

  select(slot, id, render = true) {
    slot.sel = this.catalog.get(id) ? id : null;
    slot.loading?.reset();
    if (render) {
      this.renderSlot(slot);
      this.layout();
    }
    this.onChange?.();
  }

  reset() {
    if (!this.slotSize) return;
    this.viewState = homeViewState(this.catalog.extent, ...this.slotSize);
    this.update();
  }

  setRearrange(on) {
    this.rearrange = on;
    this.root.classList.toggle("rearranging", on);
    this.root.querySelector(".rearrange-banner").hidden = !on;
    this.root.querySelector("#rearrange-toggle").checked = on;
    for (const s of this.slots) if (s.el) s.el.draggable = on && !!s.sel;
    this.layout();
  }

  swap(i, j) {
    [this.slots[i], this.slots[j]] = [this.slots[j], this.slots[i]];
    this.renderSlots();
    this.onChange?.();
  }

  // ----- DOM -----------------------------------------------------------

  renderSlots() {
    this.container.style.setProperty("--cols", this.cols);
    this.container.replaceChildren(...this.slots.map((s) => this.slotElement(s)));
    const last = this.slots.slice(-this.cols);
    this.root.querySelector("#remove-row").disabled = !(this.slots.length > this.cols && last.every((s) => !s.sel));
    this.layout();
    this.onChange?.();
  }

  slotElement(slot) {
    if (slot.el) {
      this.renderSlot(slot);
      return slot.el;
    }
    const el = document.createElement("div");
    el.className = "slot";
    el.innerHTML = `
      <div class="slot-head">
        <span class="drag-grip" title="Drag to rearrange" aria-hidden="true">⠿</span>
        <div class="picker-host"></div>
        <button class="icon-btn clear" title="Remove this image">×</button>
      </div>
      <div class="slot-title"></div>
      <div class="map-frame slot-frame">
        <div class="axis axis-left"></div>
        <div class="map slot-map">
          <button class="add-image" type="button"><span class="plus">+</span>Add image</button>
          <div class="scalebar"></div>
          <div class="map-message" hidden></div>
          <div class="rearrange-overlay"><span>⠿ Drag to move</span></div>
        </div>
        <div class="axis-corner"></div>
        <div class="axis axis-bottom"></div>
      </div>
      <div class="slot-key"></div>`;
    slot.el = el;
    slot.map = el.querySelector(".slot-map");
    slot.loading = new LoadingState(el.querySelector(".map-message"));
    slot.chrome = new MapChrome(el.querySelector(".slot-frame"), this.catalog, { tickSpacing: [96, 44] });
    slot.picker = new Picker(el.querySelector(".picker-host"), this.catalog, {
      placeholder: "Select an image",
      compact: true,
      onSelect: (sel) => this.select(slot, sel),
    });
    el.querySelector(".add-image").addEventListener("click", () => slot.picker.open());
    el.querySelector(".clear").addEventListener("click", () => this.select(slot, null));
    this.initDrag(slot);
    this.renderSlot(slot);
    return el;
  }

  renderSlot(slot) {
    const el = slot.el;
    if (!el) return;
    const r = this.catalog.get(slot.sel);
    slot.picker.set(slot.sel);
    el.classList.toggle("empty", !r);
    el.draggable = this.rearrange && !!r;
    el.querySelector(".clear").hidden = !r;
    el.querySelector(".add-image").hidden = !!r;
    const key = JSON.stringify(slot.sel);
    if (slot.titleKey !== key) {
      slot.titleKey = key;
      el.querySelector(".slot-title").innerHTML = r ? titleHTML(r, { compact: true }) : "";
      el.querySelector(".slot-key").innerHTML = r ? keyHTML(r, this.catalog, { source: false }) : "";
    }
    if (!r) el.querySelectorAll(".axis").forEach((a) => (a.innerHTML = ""));
    if (!r) el.querySelector(".scalebar").hidden = true;
  }

  // #region grid-drag
  initDrag(slot) {
    const el = slot.el;
    const index = () => this.slots.indexOf(slot);
    el.addEventListener("dragstart", (e) => {
      if (!this.rearrange || !slot.sel) return e.preventDefault();
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index()));
      el.classList.add("dragging");
      e.dataTransfer.setDragImage(dragLabel(this.catalog.get(slot.sel)), 12, 12);
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("dragging");
      this.container.querySelectorAll(".drop-target").forEach((t) => t.classList.remove("drop-target"));
    });
    el.addEventListener("dragover", (e) => {
      if (!this.rearrange) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      el.classList.add("drop-target");
    });
    el.addEventListener("dragleave", (e) => {
      if (!el.contains(e.relatedTarget)) el.classList.remove("drop-target");
    });
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      el.classList.remove("drop-target");
      const from = +e.dataTransfer.getData("text/plain");
      const to = index();
      if (Number.isInteger(from) && from !== to && this.slots[from]) this.swap(from, to);
    });
  }
  // #endregion grid-drag

  // ----- deck.gl views -------------------------------------------------

  // #region grid-layout
  /** Place one deck.gl view over each visible slot map; re-render. */
  layout() {
    if (!this.active) return;
    const first = this.slots.find((s) => s.map);
    if (!first) return;
    const size = [first.map.clientWidth, first.map.clientHeight];
    if (!size[0] || !size[1]) return;
    const e = this.catalog.extent;
    if (!this.viewState) {
      this.viewState = homeViewState(e, ...size);
    } else if (this.slotSize && (size[0] !== this.slotSize[0] || size[1] !== this.slotSize[1])) {
      // Keep the same ground extent visible when slots change size.
      const zoom = this.viewState.zoom + Math.log2(size[0] / this.slotSize[0]);
      this.viewState = clampViewState({ ...this.viewState, zoom }, e, ...size);
    }
    this.slotSize = size;
    this.update();
  }
  // #endregion grid-layout

  update() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.render();
    });
  }

  // #region grid-render
  render() {
    if (!this.active || !this.slotSize) return;
    const c = this.catalog;
    const canvas = this.deckEl.getBoundingClientRect();
    const [w, h] = this.slotSize;
    const views = [];
    const layers = [];
    for (const s of this.slots) {
      if (!s.map) continue;
      const p = c.get(s.sel);
      if (!p) continue;
      const b = s.map.getBoundingClientRect();
      if (b.bottom < canvas.top || b.top > canvas.bottom || b.right < canvas.left || b.left > canvas.right) continue;
      views.push(
        new MapView({
          id: s.uid,
          x: b.left - canvas.left,
          y: b.top - canvas.top,
          width: w,
          height: h,
          controller: this.rearrange ? false : CONTROLLER,
        }),
      );
      layers.push(backgroundLayer(`${s.uid}-bg`, c), ...productLayers(`${s.uid}-image`, c, p, s.loading));
      if (this.settings.labels) layers.push(...landmarkLayers(`${s.uid}-landmarks`, c, p.landmark_color));
    }
    const deckViewState = toDeckViewState(this.viewState, c);
    const viewState = Object.fromEntries(views.map((v) => [v.id, deckViewState]));
    this.deck.setProps({ views, viewState, layers });
    for (const s of this.slots) if (s.sel && s.chrome) s.chrome.update(this.viewState, w, h, this.settings.labels);
  }
  // #endregion grid-render
}

/** Drag image: a small card with the product's name. */
function dragLabel(p) {
  let el = document.getElementById("drag-label");
  if (!el) {
    el = document.createElement("div");
    el.id = "drag-label";
    document.body.append(el);
  }
  el.textContent = p ? p.label : "";
  return el;
}
