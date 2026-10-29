// Single-image viewer with a Worldview-style comparison mode: image B is
// revealed over image A by a swipe divider, by fading, or inside a lens (spy).
// A and B each have a product and a time (slot.js), so B can be the same
// image at another date: turning comparison on starts B one timestep before A.

import { Deck, MapView, PathLayer, SolidPolygonLayer } from "../vendor/deck-gl-raster.js";
import {
  CONTROLLER,
  LoadingState,
  MapChrome,
  backgroundLayer,
  clampViewState,
  fromDeckViewState,
  keyHTML,
  overlayProps,
  placeLayers,
  placeViewState,
  productLayers,
  showNotices,
  titleHTML,
  toDeckViewState,
  unproject,
  viewBounds,
} from "./mapview.js";
import { openCredentials } from "./env.js";
import { Picker } from "./picker.js";
import { Slot, slippyZoom } from "./slot.js";
import { TimeControl } from "./timecontrol.js";

const SPY_RADIUS = 130; // px

export class Viewer {
  constructor(root, catalog, place) {
    this.root = root;
    this.catalog = catalog;
    this.place = place; // the selected place (location.js), shared by the maps
    this.mapEl = root.querySelector("#viewer-map");
    this.chrome = new MapChrome(root.querySelector(".viewer-frame"), catalog);
    this.handle = root.querySelector(".swipe-handle");
    this.loading = new LoadingState(root.querySelector(".map-message"));
    this.noticeEl = root.querySelector(".map-notice");

    this.slots = {
      a: new Slot(catalog, { onChange: () => this.slotChanged("a") }),
      b: new Slot(catalog, { onChange: () => this.slotChanged("b") }),
    };
    this.timeControls = {
      a: new TimeControl(root.querySelector("#time-a"), this.slots.a),
      b: new TimeControl(root.querySelector("#time-b"), this.slots.b),
    };
    this.compare = false;
    this.mode = "swipe";
    this.opacity = 0.5;
    this.swipe = 0.5; // divider position, fraction of the map width
    this.spy = null; // lens center in px, or null when the cursor is off the map

    this.pickers = {
      a: new Picker(root.querySelector("#picker-a"), catalog, { onSelect: (s) => this.select("a", s), view: () => this.bounds }),
      b: new Picker(root.querySelector("#picker-b"), catalog, { onSelect: (s) => this.select("b", s), view: () => this.bounds }),
    };
    for (const k of ["a", "b"]) {
      root.querySelector(`#prev-${k}`).addEventListener("click", () => this.step(k, -1));
      root.querySelector(`#next-${k}`).addEventListener("click", () => this.step(k, 1));
    }
    root.querySelector("#compare-toggle").addEventListener("change", (e) => this.setCompare(e.target.checked));
    root.querySelector("#b-same-as-a").addEventListener("click", () => this.compareThroughTime());
    root.querySelector("#swap-ab").addEventListener("click", () => this.swap());
    root.querySelectorAll("#compare-mode button").forEach((b) => b.addEventListener("click", () => this.setMode(b.dataset.mode)));
    root.querySelector("#opacity-slider").addEventListener("input", (e) => {
      this.opacity = e.target.value / 100;
      this.update();
    });
    root.querySelector("#viewer-reset").addEventListener("click", () => this.reset());
    root.querySelector("#viewer-zoom-in").addEventListener("click", () => this.zoomBy(1));
    root.querySelector("#viewer-zoom-out").addEventListener("click", () => this.zoomBy(-1));
    this.initSwipe();
    this.mapEl.addEventListener("pointermove", (e) => {
      if (this.compare && this.mode === "spy") {
        const b = this.mapEl.getBoundingClientRect();
        this.spy = [e.clientX - b.left, e.clientY - b.top];
        this.update();
      }
    });
    this.mapEl.addEventListener("pointerleave", () => {
      if (this.spy) {
        this.spy = null;
        this.update();
      }
    });

    // #region viewer-deck
    this.size = [this.mapEl.clientWidth || 800, this.mapEl.clientHeight || 450];
    this.viewState = placeViewState(catalog, place.current, ...this.size);
    this.deck = new Deck({
      parent: this.mapEl,
      views: new MapView({ id: "main", controller: CONTROLLER }),
      viewState: toDeckViewState(this.viewState, catalog),
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(fromDeckViewState(viewState, catalog), catalog.limits, ...this.size);
        this.update();
        return toDeckViewState(this.viewState, catalog);
      },
      onResize: ({ width, height }) => {
        this.size = [width, height];
        this.viewState = clampViewState(this.viewState, catalog.limits, width, height);
        this.update();
      },
      layers: [],
    });
    // #endregion viewer-deck
  }

  /** Current state, for the URL: selections (slot.js) of A and B. */
  get state() {
    return { a: this.slots.a.sel, b: this.compare ? this.slots.b.sel : null, mode: this.mode };
  }

  select(k, id) {
    this.slots[k].select(this.catalog.get(id) ? id : null);
  }

  /** Restore a full selection (product and time). */
  setSel(k, sel) {
    this.slots[k].setSel(sel);
  }

  slotChanged(k) {
    this.pickers[k].set(this.slots[k].sel.id);
    this.timeControls[k].render();
    this.update();
  }

  /** Previous / next image in the product's menu group. */
  step(k, d) {
    const id = this.slots[k].sel.id;
    if (id) this.select(k, this.catalog.sibling(id, d));
  }

  /** Previous / next timestep of A (or B). */
  stepTime(k, d) {
    this.slots[k].step(d);
  }

  setCompare(on) {
    this.compare = on;
    this.root.querySelector("#compare-toggle").checked = on;
    this.root.querySelector(".compare-controls").hidden = !on;
    this.root.querySelector(".tag-a").hidden = !on;
    this.root.classList.toggle("comparing", on);
    if (on && !this.slots.b.sel.id && this.slots.a.sel.id) this.compareThroughTime();
    this.update();
  }

  // #region compare-through-time
  /**
   * B = A's image one timestep earlier (the timestep before A's with data in
   * view), or, for a product without time, the next image in A's group.
   */
  compareThroughTime() {
    const a = this.slots.a;
    if (a.product?.time && a.steps && a.sel.t) {
      const prev = a.steps.neighbor(a.sel.t, -1);
      this.slots.b.setSel({ ...a.sel, t: prev ?? a.sel.t, t2: null, auto: !prev });
    } else if (a.product?.time && !a.steps) {
      this.slots.b.setSel({ ...a.sel });
    } else {
      this.select("b", this.catalog.sibling(a.sel.id, 1));
    }
  }
  // #endregion compare-through-time

  /** Swap A and B (product and time). */
  swap() {
    const a = { ...this.slots.a.sel };
    const b = { ...this.slots.b.sel };
    this.slots.a.setSel(b);
    this.slots.b.setSel(a);
  }

  setMode(mode) {
    this.mode = mode;
    this.root.querySelectorAll("#compare-mode button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
    this.root.querySelector("#opacity-slider").hidden = mode !== "opacity";
    this.update();
  }

  zoomBy(d) {
    this.viewState = clampViewState({ ...this.viewState, zoom: this.viewState.zoom + d }, this.catalog.limits, ...this.size);
    this.update();
  }

  /** Back to the selected place (or Greater New Haven). */
  reset() {
    this.viewState = placeViewState(this.catalog, this.place.current, ...this.size);
    this.update();
  }

  // #region swipe-handle
  initSwipe() {
    let dragging = false;
    const move = (e) => {
      const b = this.mapEl.getBoundingClientRect();
      this.swipe = Math.min(1, Math.max(0, (e.clientX - b.left) / b.width));
      this.update();
    };
    this.handle.addEventListener("pointerdown", (e) => {
      dragging = true;
      this.handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    this.handle.addEventListener("pointermove", (e) => dragging && move(e));
    this.handle.addEventListener("pointerup", () => (dragging = false));
    this.handle.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        this.swipe = Math.min(1, Math.max(0, this.swipe + (e.key === "ArrowLeft" ? -0.02 : 0.02)));
        this.update();
      }
    });
  }
  // #endregion swipe-handle

  // #region compare-layers
  /** The product of slot k if it can be drawn (else null; slot.status() says why). */
  drawable(k) {
    const slot = this.slots[k];
    const p = slot.product;
    if (!p) return null;
    const st = slot.status();
    return st ? null : p;
  }

  extra(k) {
    return { time: this.slots[k].ctx(), view: this.bounds, onReady: () => this.update() };
  }

  layers() {
    const c = this.catalog;
    const [w, h] = this.size;
    const layers = [backgroundLayer("bg", c)];
    const a = this.drawable("a");
    if (a) layers.push(...productLayers("a", c, a, this.loading, undefined, this.extra("a")));
    const b = this.compare && this.drawable("b");
    if (b) {
      let overlay = null;
      let lens = null;
      if (this.mode === "swipe") {
        overlay = { clipX: unproject(this.viewState, w, h, this.swipe * w, 0)[0] };
      } else if (this.mode === "opacity") {
        overlay = { opacity: this.opacity };
      } else if (this.spy) {
        const [cx, cy] = unproject(this.viewState, w, h, ...this.spy);
        const r = SPY_RADIUS / 2 ** this.viewState.zoom;
        const ring = Array.from({ length: 97 }, (_, i) =>
          c.worldToLngLat(cx + r * Math.cos((i * Math.PI) / 48), cy + r * Math.sin((i * Math.PI) / 48)),
        );
        layers.push(new SolidPolygonLayer({ id: "spy-mask", operation: "mask", data: [{ polygon: ring }], getPolygon: (d) => d.polygon }));
        lens = new PathLayer({
          id: "spy-ring",
          data: [{ path: ring }],
          getPath: (d) => d.path,
          getColor: [255, 255, 255, 230],
          getWidth: 2,
          widthUnits: "pixels",
        });
        overlay = { maskId: "spy-mask" };
      }
      if (overlay) {
        // B's own no-data background, so A does not show through B's transparent pixels.
        if (this.mode !== "opacity") layers.push(backgroundLayer("bg-b", c, overlayProps(c, overlay)));
        layers.push(...productLayers("b", c, b, this.loading, overlay, this.extra("b")));
        if (lens) layers.push(lens);
      }
    }
    layers.push(...placeLayers("place", this.place.current));
    return layers;
  }
  // #endregion compare-layers

  // #region render-throttle
  update() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.render();
    });
  }
  // #endregion render-throttle

  render() {
    const c = this.catalog;
    const [w, h] = this.size;
    this.bounds = viewBounds(this.viewState, c, w, h);
    const z = slippyZoom(this.viewState.zoom);
    this.slots.a.setView(this.bounds, z);
    if (this.compare) this.slots.b.setView(this.bounds, z);
    this.deck.setProps({ viewState: toDeckViewState(this.viewState, c), layers: this.layers() });
    showNotices(
      this.noticeEl,
      [
        { tag: this.compare ? "A" : "", status: this.slots.a.status() },
        ...(this.compare && this.slots.b.product ? [{ tag: "B", status: this.slots.b.status() }] : []),
      ],
      (name) => openCredentials(name),
    );
    this.chrome.update(this.viewState, w, h);

    const swipe = this.compare && this.mode === "swipe";
    this.handle.hidden = !swipe;
    if (swipe) this.handle.style.left = `${this.swipe * w}px`;
    this.mapEl.classList.toggle("spy", this.compare && this.mode === "spy");

    // Titles and keys (HTML), only rebuilt when the selection changes.
    const ra = this.slots.a.product;
    const rb = this.compare ? this.slots.b.product : null;
    const ta = this.slots.a.timeLabel();
    const tb = rb ? this.slots.b.timeLabel() : "";
    const key = JSON.stringify([ra?.id, ta, this.slots.a.sel.t, rb?.id, tb]);
    if (key !== this.titlesKey) {
      this.titlesKey = key;
      const tag = (t) => (rb ? `<span class="slot-tag tag-${t.toLowerCase()}">${t}</span>` : "");
      const times = { A: [ta, this.slots.a.sel.t], B: [tb, this.slots.b.sel.t] };
      const col = (p, t) =>
        p ? `<div class="title-block">${titleHTML(p, { tag: tag(t), time: times[t][0], t: times[t][1] })}</div>` : "";
      const keyCol = (p, t) => (p ? `<div class="key-block">${keyHTML(p, c, { tag: tag(t) })}</div>` : "");
      this.root.querySelector(".viewer-titles").innerHTML = col(ra, "A") + col(rb, "B");
      this.root.querySelector(".viewer-legends").innerHTML = keyCol(ra, "A") + keyCol(rb, "B");
    }
    this.onChange?.();
  }
}
