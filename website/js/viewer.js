// Single-image viewer with a Worldview-style comparison mode: image B is
// revealed over image A by a swipe divider, by fading, or inside a lens (spy).

import {
  LoadingState,
  MapChrome,
  backgroundLayer,
  clampViewState,
  homeViewState,
  keyHTML,
  landmarkLayers,
  productLayers,
  titleHTML,
  unproject,
} from "./mapview.js";
import { Picker } from "./picker.js";

const { Deck, OrthographicView, ClipExtension, MaskExtension, PathLayer, SolidPolygonLayer } = deck;

const SPY_RADIUS = 130; // px
const clipExtension = new ClipExtension();
const maskExtension = new MaskExtension();

export class Viewer {
  constructor(root, catalog, settings) {
    this.root = root;
    this.catalog = catalog;
    this.settings = settings; // shared { labels }
    this.mapEl = root.querySelector("#viewer-map");
    this.chrome = new MapChrome(root.querySelector(".viewer-frame"), catalog);
    this.handle = root.querySelector(".swipe-handle");
    this.loading = new LoadingState(root.querySelector(".map-message"));

    this.sel = { a: null, b: null }; // product ids
    this.compare = false;
    this.mode = "swipe";
    this.opacity = 0.5;
    this.swipe = 0.5; // divider position, fraction of the map width
    this.spy = null; // lens center in px, or null when the cursor is off the map

    this.pickers = {
      a: new Picker(root.querySelector("#picker-a"), catalog, { onSelect: (s) => this.select("a", s) }),
      b: new Picker(root.querySelector("#picker-b"), catalog, { onSelect: (s) => this.select("b", s) }),
    };
    for (const k of ["a", "b"]) {
      root.querySelector(`#prev-${k}`).addEventListener("click", () => this.step(k, -1));
      root.querySelector(`#next-${k}`).addEventListener("click", () => this.step(k, 1));
    }
    root.querySelector("#compare-toggle").addEventListener("change", (e) => this.setCompare(e.target.checked));
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

    this.size = [this.mapEl.clientWidth || 800, this.mapEl.clientHeight || 450];
    this.viewState = homeViewState(catalog.extent, ...this.size);
    this.deck = new Deck({
      parent: this.mapEl,
      views: new OrthographicView({ id: "main", flipY: false, controller: { inertia: 250 } }),
      viewState: this.viewState,
      onViewStateChange: ({ viewState }) => {
        this.viewState = clampViewState(viewState, catalog.extent, ...this.size);
        this.update();
        return this.viewState;
      },
      onResize: ({ width, height }) => {
        this.size = [width, height];
        this.viewState = clampViewState(this.viewState, catalog.extent, width, height);
        this.update();
      },
      layers: [],
    });
  }

  /** Current state, for the URL. */
  get state() {
    return { a: this.sel.a, b: this.compare ? this.sel.b : null, mode: this.mode };
  }

  select(k, id) {
    this.sel[k] = this.catalog.get(id) ? id : null;
    this.pickers[k].set(this.sel[k]);
    this.update();
  }

  step(k, d) {
    if (this.sel[k]) this.select(k, this.catalog.sibling(this.sel[k], d));
  }

  setCompare(on) {
    this.compare = on;
    this.root.querySelector("#compare-toggle").checked = on;
    this.root.querySelector(".compare-controls").hidden = !on;
    this.root.querySelector(".tag-a").hidden = !on;
    this.root.classList.toggle("comparing", on);
    if (on && !this.sel.b && this.sel.a) this.select("b", this.catalog.sibling(this.sel.a, 1));
    this.update();
  }

  setMode(mode) {
    this.mode = mode;
    this.root.querySelectorAll("#compare-mode button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
    this.root.querySelector("#opacity-slider").hidden = mode !== "opacity";
    this.update();
  }

  zoomBy(d) {
    this.viewState = clampViewState({ ...this.viewState, zoom: this.viewState.zoom + d }, this.catalog.extent, ...this.size);
    this.update();
  }

  reset() {
    this.viewState = homeViewState(this.catalog.extent, ...this.size);
    this.update();
  }

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

  layers() {
    const c = this.catalog;
    const [w, h] = this.size;
    const layers = [backgroundLayer("bg", c.extent)];
    const a = c.get(this.sel.a);
    if (a) layers.push(...productLayers("a", c, a, this.loading));
    const b = this.compare && c.get(this.sel.b);
    if (b) {
      let props = null;
      let lens = null;
      if (this.mode === "swipe") {
        const x = unproject(this.viewState, w, h, this.swipe * w, 0)[0];
        props = { extensions: [clipExtension], clipBounds: [x, -1e8, 1e8, 1e8] };
      } else if (this.mode === "opacity") {
        props = { opacity: this.opacity };
      } else if (this.spy) {
        const [cx, cy] = unproject(this.viewState, w, h, ...this.spy);
        const r = SPY_RADIUS / 2 ** this.viewState.zoom;
        const ring = Array.from({ length: 97 }, (_, i) => [cx + r * Math.cos((i * Math.PI) / 48), cy + r * Math.sin((i * Math.PI) / 48)]);
        layers.push(new SolidPolygonLayer({ id: "spy-mask", operation: "mask", data: [{ polygon: ring }], getPolygon: (d) => d.polygon }));
        lens = new PathLayer({
          id: "spy-ring",
          data: [{ path: ring }],
          getPath: (d) => d.path,
          getColor: [255, 255, 255, 230],
          getWidth: 2,
          widthUnits: "pixels",
        });
        props = { extensions: [maskExtension], maskId: "spy-mask" };
      }
      if (props) {
        // B's own no-data background, so A does not show through B's transparent pixels.
        if (this.mode !== "opacity") layers.push(backgroundLayer("bg-b", c.extent).clone(props));
        layers.push(...productLayers("b", c, b, this.loading, props));
        if (lens) layers.push(lens);
      }
    }
    if (this.settings.labels) layers.push(...landmarkLayers("landmarks", c, a?.landmark_color));
    return layers;
  }

  update() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.render();
    });
  }

  render() {
    const c = this.catalog;
    const [w, h] = this.size;
    this.deck.setProps({ viewState: this.viewState, layers: this.layers() });
    this.chrome.update(this.viewState, w, h, this.settings.labels);

    const swipe = this.compare && this.mode === "swipe";
    this.handle.hidden = !swipe;
    if (swipe) this.handle.style.left = `${this.swipe * w}px`;
    this.mapEl.classList.toggle("spy", this.compare && this.mode === "spy");

    // Titles and keys (HTML), only rebuilt when the selection changes.
    const ra = c.get(this.sel.a);
    const rb = this.compare ? c.get(this.sel.b) : null;
    const key = JSON.stringify([this.sel.a, rb && this.sel.b]);
    if (key !== this.titlesKey) {
      this.titlesKey = key;
      const tag = (t) => (rb ? `<span class="slot-tag tag-${t.toLowerCase()}">${t}</span>` : "");
      const col = (p, t) => (p ? `<div class="title-block">${titleHTML(p, { tag: tag(t) })}</div>` : "");
      const keyCol = (p, t) => (p ? `<div class="key-block">${keyHTML(p, c, { tag: tag(t) })}</div>` : "");
      this.root.querySelector(".viewer-titles").innerHTML = col(ra, "A") + col(rb, "B");
      this.root.querySelector(".viewer-legends").innerHTML = keyCol(ra, "A") + keyCol(rb, "B");
    }
    this.onChange?.();
  }
}
