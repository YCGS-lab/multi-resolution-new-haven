// Grid of images with synchronized pan / zoom.
//
// All slots share ONE deck.gl canvas (fixed behind the page) with one
// OrthographicView per slot, placed over the slot's map area; the slot's own
// HTML (picker, title, axes, key) sits on top, and the map area is a
// transparent hole that lets pointer events through to deck.gl. This keeps a
// single WebGL context however many slots there are.

import { loadImage } from "./catalog.js";
import { MapChrome, backgroundLayer, clampViewState, homeViewState, imageLayers, keyHTML, landmarkLayers, titleHTML } from "./mapview.js";
import { Picker } from "./picker.js";

const { Deck, OrthographicView } = deck;

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

    this.deck = new Deck({
      parent: this.deckEl,
      views: [],
      viewState: {},
      layers: [],
      layerFilter: ({ layer, viewport }) => layer.id.startsWith(`${viewport.id}-`),
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(viewState, catalog.extent, ...this.slotSize);
        this.update();
        return this.viewState;
      },
    });

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
    return { uid: `s${nextUid++}`, sel: null, shown: null, error: null };
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

  select(slot, sel, render = true) {
    slot.sel = sel;
    slot.error = null;
    const r = this.catalog.resolve(sel);
    if (r) {
      loadImage(r.meta.src).then(
        (img) => {
          if (slot.sel !== sel) return;
          slot.shown = { r, img };
          this.renderSlot(slot);
          this.layout();
        },
        () => {
          if (slot.sel !== sel) return;
          slot.shown = null;
          slot.error = `Could not load ${r.meta.src}`;
          this.renderSlot(slot);
          this.layout();
        },
      );
    } else {
      slot.shown = null;
    }
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
    const r = this.catalog.resolve(slot.sel);
    slot.picker.set(slot.sel);
    el.classList.toggle("empty", !r);
    el.draggable = this.rearrange && !!r;
    el.querySelector(".clear").hidden = !r;
    el.querySelector(".add-image").hidden = !!r;
    const key = JSON.stringify(slot.sel);
    if (slot.titleKey !== key) {
      slot.titleKey = key;
      el.querySelector(".slot-title").innerHTML = r ? titleHTML(r, this.catalog, { compact: true }) : "";
      el.querySelector(".slot-key").innerHTML = r ? keyHTML(r, { source: false }) : "";
    }
    const msg = el.querySelector(".map-message");
    msg.hidden = !(r && (!slot.shown || slot.error));
    msg.textContent = slot.error || "Loading…";
    if (!r) el.querySelectorAll(".axis").forEach((a) => (a.innerHTML = ""));
    if (!r) el.querySelector(".scalebar").hidden = true;
  }

  initDrag(slot) {
    const el = slot.el;
    const index = () => this.slots.indexOf(slot);
    el.addEventListener("dragstart", (e) => {
      if (!this.rearrange || !slot.sel) return e.preventDefault();
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index()));
      el.classList.add("dragging");
      if (slot.shown) e.dataTransfer.setDragImage(thumbnail(slot.shown.img), 96, 54);
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

  // ----- deck.gl views -------------------------------------------------

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

  update() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.render();
    });
  }

  render() {
    if (!this.active || !this.slotSize) return;
    const c = this.catalog;
    const canvas = this.deckEl.getBoundingClientRect();
    const [w, h] = this.slotSize;
    const views = [];
    const layers = [];
    for (const s of this.slots) {
      if (!s.map) continue;
      if (!s.shown) continue;
      const b = s.map.getBoundingClientRect();
      if (b.bottom < canvas.top || b.top > canvas.bottom || b.right < canvas.left || b.left > canvas.right) continue;
      views.push(
        new OrthographicView({
          id: s.uid,
          x: b.left - canvas.left,
          y: b.top - canvas.top,
          width: w,
          height: h,
          flipY: false,
          controller: this.rearrange ? false : { inertia: 250 },
        }),
      );
      layers.push(backgroundLayer(`${s.uid}-bg`, c.extent), ...imageLayers(`${s.uid}-image`, s.shown.r, s.shown.img, c));
      if (this.settings.labels) layers.push(...landmarkLayers(`${s.uid}-landmarks`, c, s.shown.r.meta.landmark_color));
    }
    const viewState = Object.fromEntries(views.map((v) => [v.id, this.viewState]));
    this.deck.setProps({ views, viewState, layers });
    for (const s of this.slots) if (s.shown && s.chrome) s.chrome.update(this.viewState, w, h, this.settings.labels);
  }
}

function thumbnail(img) {
  let canvas = document.getElementById("drag-thumbnail");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "drag-thumbnail";
    canvas.width = 192;
    canvas.height = 108;
    canvas.style.cssText = "position:fixed;left:-1000px;top:0";
    document.body.append(canvas);
  }
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#d0d0d0";
  ctx.fillRect(0, 0, 192, 108);
  ctx.drawImage(img, 0, 0, 192, 108);
  return canvas;
}
