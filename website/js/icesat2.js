// ICESat-2 tab: the sample beam passes on a map (left; click one to select
// it), and the selected beam's ATL03 photons with their ATL08 classes as a
// cross-section (right; elevation against distance along track). An arrow on
// the map and a dashed line in the profile mark the same point along track:
// drag either one and the other follows.
//
// Data: website/image-data/icesat2-profiles.json (scripts/icesat2/create-cog.py,
// from the files download.py saved; nothing is fetched from ICESat-2 services).

import { Deck, MapView, PathLayer } from "../vendor/deck-gl-raster.js";
import {
  CONTROLLER,
  MapChrome,
  backgroundLayer,
  clampViewState,
  fromDeckViewState,
  homeViewState,
  productLayers,
  toDeckViewState,
} from "./mapview.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
const hexRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const NEAR_M = 15; // half-width of the along-track window for the readout

export class Icesat2 {
  constructor(root, catalog) {
    this.root = root;
    this.catalog = catalog;
    this.active = false;
    this.data = null;
    this.line = null; // selected line
    this.pos = 0; // cursor: meters along track
    this.xr = null; // profile x range [m0, m1] (zoom), null = whole line
    this.mapEl = root.querySelector("#is2-map");
    this.arrow = root.querySelector(".is2-arrow");
    this.canvas = root.querySelector("#is2-profile");
    this.chrome = new MapChrome(root.querySelector(".is2-map-frame"), catalog, { tickSpacing: [96, 44] });
    this.showCanopy = root.querySelector("#is2-canopy");
    this.showCanopy.addEventListener("change", () => this.update());
    root.querySelector("#is2-zoom-reset").addEventListener("click", () => {
      this.xr = null;
      this.drawProfile();
    });
    this.initArrow();
    this.initProfile();
    new ResizeObserver(() => this.active && this.drawProfile()).observe(this.canvas.parentElement);
  }

  get state() {
    return this.line ? `${this.line.n}@${Math.round(this.pos)}` : null;
  }

  restore(s) {
    const [n, pos] = s.split("@");
    this.pending = { n: +n, pos: +pos || null };
  }

  async setActive(on) {
    this.active = on;
    if (!on) return;
    this.ensureDeck();
    if (!this.data && !this.loading) await this.load();
    this.update();
    this.drawProfile();
  }

  async load() {
    this.loading = true;
    try {
      const res = await fetch("image-data/icesat2-profiles.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
    } catch (err) {
      this.root.querySelector(".is2-body").innerHTML = `<div class="fatal"><p>No ICESat-2 profiles (${esc(err.message)}).</p>
        <p>Run <code>uv run scripts/icesat2/download.py</code> and <code>uv run scripts/icesat2/create-cog.py</code>.</p></div>`;
      return;
    } finally {
      this.loading = false;
    }
    for (const line of this.data.lines) {
      const p = line.photons;
      line.d = Float32Array.from(p.dist_dm, (v) => v / 10);
      line.h = Float32Array.from(p.height_dm, (v) => v / 10);
      line.c = Uint8Array.from(p.cls, (ch) => +ch);
      line.rgb = hexRgb(line.color);
    }
    this.classes = [...this.data.classes].sort((a, b) => a.order - b.order);
    this.fitTracks();
    this.renderList();
    const want = this.pending && this.data.lines.find((l) => l.n === this.pending.n);
    this.selectLine(want ?? this.data.lines[0], this.pending?.pos);
    this.pending = null;
  }

  renderList() {
    const el = this.root.querySelector(".is2-lines");
    el.innerHTML = this.data.lines
      .map(
        (l) => `<button type="button" class="is2-line" data-n="${l.n}" style="--line:${l.color}" aria-pressed="false">
          <span class="is2-num">${l.n}</span>
          <span class="is2-desc"><b>${esc(l.time)} UTC</b><br />RGT ${l.rgt}, cycle ${l.cycle}, beam ${esc(l.beam)} (${l.strength})</span>
        </button>`,
      )
      .join("");
    el.querySelectorAll(".is2-line").forEach((b) =>
      b.addEventListener("click", () => this.selectLine(this.data.lines.find((l) => l.n === +b.dataset.n))),
    );
  }

  selectLine(line, pos = null) {
    this.line = line;
    this.pos = pos ?? line.length_m / 2;
    this.xr = null;
    this.root.querySelectorAll(".is2-line").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.n === line.n)));
    const counts = {};
    for (const c of line.c) counts[c] = (counts[c] ?? 0) + 1;
    this.root.querySelector(".is2-legend").innerHTML = [...this.classes]
      .reverse()
      .map((c) => `<span class="lg-entry"><span class="swatch round" style="background:${c.color}"></span>${esc(c.label)} (${(counts[c.code] ?? 0).toLocaleString()})</span>`)
      .join("");
    this.root.querySelector(".is2-title").innerHTML = `
      <h2 class="title">ICESat-2 photons with ATL08 classification: sample line ${line.n}</h2>
      <div class="subtitle">${esc(line.time)} UTC, RGT ${line.rgt}, cycle ${line.cycle}, beam ${esc(line.beam)} (${line.strength}, spot ${line.spot});
        ${line.d.length.toLocaleString()} ATL03 photons; laser shots every ~0.7 m along track, ~11 m footprint</div>`;
    this.update();
    this.drawProfile();
    this.onChange?.();
  }

  // ------------------------------------------------------------------
  // Map
  // ------------------------------------------------------------------

  ensureDeck() {
    if (this.deck) return;
    const c = this.catalog;
    this.size = [this.mapEl.clientWidth || 600, this.mapEl.clientHeight || 500];
    this.viewState = homeViewState(c.extent, ...this.size);
    this.deck = new Deck({
      parent: this.mapEl,
      views: new MapView({ id: "is2", controller: { ...CONTROLLER, doubleClickZoom: false } }),
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
      getCursor: ({ isHovering, isDragging }) => (isHovering ? "pointer" : isDragging ? "grabbing" : "grab"),
      onClick: (info) => {
        if (info.object?.line) this.selectLine(info.object.line, this.nearestOn(info.object.line, info.x, info.y));
      },
      layers: [],
    });
  }

  /** Zoom the map to the beams. */
  fitTracks() {
    const c = this.catalog;
    const pts = this.data.lines.flatMap((l) => l.track.map((v) => c.lonLatToWorld(v[0], v[1])));
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const pad = 600; // m
    const box = [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
    const [w, h] = this.size;
    const zoom = Math.log2(Math.min(w / (box[2] - box[0]), h / (box[3] - box[1])));
    this.viewState = clampViewState({ target: [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2, 0], zoom }, c.extent, w, h);
  }

  basemapLayers() {
    const c = this.catalog;
    const base = c.get("icesat2/canopy_height_allyears") ?? c.get("streetmap/osm");
    if (!base) return [];
    const layers = this.showCanopy.checked && base.id.startsWith("icesat2/") ? base.layers : base.layers.slice(0, 1);
    return productLayers("is2-base", c, { ...base, layers }, null);
  }

  update() {
    if (!this.deck || !this.data) return;
    if (this.pendingFrame) return;
    this.pendingFrame = requestAnimationFrame(() => {
      this.pendingFrame = null;
      this.render();
    });
  }

  render() {
    const c = this.catalog;
    const lines = this.data.lines;
    const sel = this.line;
    const data = lines.map((line) => ({ line, path: line.track.map((v) => [v[0], v[1]]) }));
    const layers = [
      backgroundLayer("is2-bg", c),
      ...this.basemapLayers(),
      new PathLayer({
        id: "is2-halo",
        data,
        getPath: (d) => d.path,
        getColor: [255, 255, 255, 230],
        getWidth: (d) => (d.line === sel ? 11 : 8),
        widthUnits: "pixels",
        capRounded: true,
        updateTriggers: { getWidth: sel?.n },
      }),
      new PathLayer({
        id: "is2-tracks",
        data,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 90],
        getPath: (d) => d.path,
        getColor: (d) => [...d.line.rgb, d.line === sel ? 255 : 150],
        getWidth: (d) => (d.line === sel ? 6 : 4),
        widthUnits: "pixels",
        capRounded: true,
        updateTriggers: { getColor: sel?.n, getWidth: sel?.n },
      }),
    ];
    this.deck.setProps({ viewState: toDeckViewState(this.viewState, c), layers });
    this.chrome.update(this.viewState, ...this.size, true);
    this.placeArrow();
  }

  /** Screen position (px in the map) of a lon / lat. */
  project(lon, lat) {
    const vs = this.viewState;
    if (!vs) return [0, 0];
    const [x, y] = this.catalog.lonLatToWorld(lon, lat);
    const s = 2 ** vs.zoom;
    return [this.size[0] / 2 + (x - vs.target[0]) * s, this.size[1] / 2 - (y - vs.target[1]) * s];
  }

  /** Lon / lat and heading (degrees clockwise from screen up) at a distance along a line. */
  along(line, pos) {
    const tr = line.track;
    let i = 1;
    while (i < tr.length - 1 && tr[i][2] < pos) i++;
    const [a, b] = [tr[i - 1], tr[i]];
    const f = b[2] > a[2] ? Math.min(1, Math.max(0, (pos - a[2]) / (b[2] - a[2]))) : 0;
    const lon = a[0] + f * (b[0] - a[0]);
    const lat = a[1] + f * (b[1] - a[1]);
    const [x0, y0] = this.project(a[0], a[1]);
    const [x1, y1] = this.project(b[0], b[1]);
    return { lon, lat, heading: (Math.atan2(x1 - x0, -(y1 - y0)) * 180) / Math.PI };
  }

  /** Distance along `line` of the track point nearest to a screen point. */
  nearestOn(line, px, py) {
    let best = Infinity;
    let pos = this.pos;
    const tr = line.track;
    for (let i = 1; i < tr.length; i++) {
      const [ax, ay] = this.project(tr[i - 1][0], tr[i - 1][1]);
      const [bx, by] = this.project(tr[i][0], tr[i][1]);
      const dx = bx - ax;
      const dy = by - ay;
      const L = dx * dx + dy * dy;
      const f = L ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L)) : 0;
      const d = (ax + f * dx - px) ** 2 + (ay + f * dy - py) ** 2;
      if (d < best) {
        best = d;
        pos = tr[i - 1][2] + f * (tr[i][2] - tr[i - 1][2]);
      }
    }
    return pos;
  }

  // #region is2-arrow
  placeArrow() {
    const line = this.line;
    if (!line || !this.size) return;
    const { lon, lat, heading } = this.along(line, this.pos);
    const [x, y] = this.project(lon, lat);
    const inside = x >= -20 && y >= -20 && x <= this.size[0] + 20 && y <= this.size[1] + 20;
    this.arrow.hidden = !inside;
    this.arrow.style.transform = `translate(${x}px, ${y}px) rotate(${heading}deg)`;
    this.arrow.style.setProperty("--line", line.color);
    this.arrow.setAttribute("aria-valuenow", String(Math.round(this.pos)));
    this.arrow.setAttribute("aria-valuetext", `${(this.pos / 1000).toFixed(2)} km along track`);
  }

  initArrow() {
    let dragging = false;
    const move = (e) => {
      const b = this.mapEl.getBoundingClientRect();
      this.setPos(this.nearestOn(this.line, e.clientX - b.left, e.clientY - b.top));
    };
    this.arrow.addEventListener("pointerdown", (e) => {
      dragging = true;
      this.arrow.setPointerCapture(e.pointerId);
      this.arrow.classList.add("dragging");
      e.preventDefault();
      e.stopPropagation();
    });
    this.arrow.addEventListener("pointermove", (e) => dragging && move(e));
    const stop = () => {
      dragging = false;
      this.arrow.classList.remove("dragging");
      this.onChange?.();
    };
    this.arrow.addEventListener("pointerup", stop);
    this.arrow.addEventListener("pointercancel", stop);
    this.arrow.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 500 : 50;
      if (e.key === "ArrowRight" || e.key === "ArrowUp") this.setPos(this.pos + step);
      else if (e.key === "ArrowLeft" || e.key === "ArrowDown") this.setPos(this.pos - step);
      else return;
      e.preventDefault();
    });
  }
  // #endregion is2-arrow

  setPos(pos) {
    if (!this.line) return;
    this.pos = Math.max(0, Math.min(this.line.length_m, pos));
    this.placeArrow();
    this.drawProfile();
  }

  // ------------------------------------------------------------------
  // Profile
  // ------------------------------------------------------------------

  // #region is2-profile-events
  initProfile() {
    let dragging = false;
    const toPos = (e) => {
      const r = this.canvas.getBoundingClientRect();
      const m = this.margin;
      const [x0, x1] = this.xRange();
      return x0 + ((e.clientX - r.left - m.l) / (r.width - m.l - m.r)) * (x1 - x0);
    };
    this.canvas.addEventListener("pointerdown", (e) => {
      if (!this.line) return;
      dragging = true;
      this.canvas.setPointerCapture(e.pointerId);
      this.setPos(toPos(e));
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (dragging) this.setPos(toPos(e));
      else if (this.line) {
        const r = this.canvas.getBoundingClientRect();
        const near = Math.abs(e.clientX - r.left - this.cursorX) < 8;
        this.canvas.style.cursor = near ? "ew-resize" : "crosshair";
      }
    });
    const stop = () => {
      if (dragging) this.onChange?.();
      dragging = false;
    };
    this.canvas.addEventListener("pointerup", stop);
    this.canvas.addEventListener("pointercancel", stop);
    this.canvas.addEventListener(
      "wheel",
      (e) => {
        if (!this.line) return;
        e.preventDefault();
        const [x0, x1] = this.xRange();
        const at = toPos(e);
        const k = Math.exp(e.deltaY * 0.0015);
        const span = Math.min(this.line.length_m, Math.max(50, (x1 - x0) * k));
        let a = at - ((at - x0) / (x1 - x0)) * span;
        a = Math.max(0, Math.min(this.line.length_m - span, a));
        this.xr = span >= this.line.length_m ? null : [a, a + span];
        this.drawProfile();
      },
      { passive: false },
    );
    this.canvas.addEventListener("dblclick", () => {
      this.xr = null;
      this.drawProfile();
    });
    this.canvas.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 500 : 50;
      if (e.key === "ArrowRight") this.setPos(this.pos + step);
      else if (e.key === "ArrowLeft") this.setPos(this.pos - step);
      else return;
      e.preventDefault();
    });
  }
  // #endregion is2-profile-events

  xRange() {
    return this.xr ?? [0, this.line?.length_m ?? 1];
  }

  // #region is2-profile-draw
  drawProfile() {
    const line = this.line;
    const cv = this.canvas;
    if (!line || !this.active) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.parentElement.clientWidth;
    const H = cv.parentElement.clientHeight;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr);
      cv.height = Math.round(H * dpr);
      cv.style.width = `${W}px`;
      cv.style.height = `${H}px`;
    }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const m = (this.margin = { l: 58, r: 14, t: 12, b: 42 });
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const [x0, x1] = this.xRange();
    const [lo, hi] = line.height_range;
    const sx = (d) => m.l + ((d - x0) / (x1 - x0)) * pw;
    const sy = (h) => m.t + (1 - (h - lo) / (hi - lo)) * ph;

    // grid and axes
    ctx.font = "12px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
    ctx.fillStyle = "#333";
    ctx.strokeStyle = "#e6e6e6";
    ctx.lineWidth = 1;
    const xt = niceTicks(x0 / 1000, x1 / 1000, Math.max(3, Math.floor(pw / 90)));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const v of xt.ticks) {
      const x = Math.round(sx(v * 1000)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, m.t);
      ctx.lineTo(x, m.t + ph);
      ctx.stroke();
      ctx.fillText(v.toFixed(xt.decimals), x, m.t + ph + 6);
    }
    const yt = niceTicks(lo, hi, Math.max(3, Math.floor(ph / 45)));
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const v of yt.ticks) {
      const y = Math.round(sy(v)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(m.l, y);
      ctx.lineTo(m.l + pw, y);
      ctx.stroke();
      ctx.fillText(v.toFixed(yt.decimals), m.l - 6, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("Distance along track (km)", m.l + pw / 2, H - 2);
    ctx.save();
    ctx.translate(14, m.t + ph / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = "middle";
    ctx.fillText("Elevation (m, EGM2008 geoid)", 0, 0);
    ctx.restore();

    // photons, recessive classes first
    ctx.save();
    ctx.beginPath();
    ctx.rect(m.l, m.t, pw, ph);
    ctx.clip();
    const size = Math.max(1.5, Math.min(3.5, (pw / ((x1 - x0) / 0.7)) * 1.5));
    for (const c of this.classes) {
      ctx.fillStyle = c.color;
      const s = c.code === 0 || c.code === 4 ? size * 0.75 : size;
      const { d, h, c: cls } = line;
      for (let i = 0; i < d.length; i++) {
        if (cls[i] !== c.code || d[i] < x0 || d[i] > x1) continue;
        ctx.fillRect(sx(d[i]) - s / 2, sy(h[i]) - s / 2, s, s);
      }
    }
    ctx.restore();
    ctx.strokeStyle = "#999";
    ctx.strokeRect(m.l + 0.5, m.t + 0.5, pw, ph);

    // cursor: dashed vertical line
    this.cursorX = sx(this.pos);
    if (this.cursorX >= m.l && this.cursorX <= m.l + pw) {
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "#111";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(this.cursorX, m.t);
      ctx.lineTo(this.cursorX, m.t + ph);
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = line.color;
      ctx.beginPath();
      ctx.moveTo(this.cursorX - 7, m.t);
      ctx.lineTo(this.cursorX + 7, m.t);
      ctx.lineTo(this.cursorX, m.t + 9);
      ctx.closePath();
      ctx.fill();
    }
    this.readout();
    this.root.querySelector("#is2-zoom-reset").disabled = !this.xr;
  }
  // #endregion is2-profile-draw

  /** Position and heights near the cursor. */
  readout() {
    const line = this.line;
    const { lon, lat } = this.along(line, this.pos);
    const near = (codes) => {
      const v = [];
      for (let i = 0; i < line.d.length; i++) if (Math.abs(line.d[i] - this.pos) <= NEAR_M && codes.includes(line.c[i])) v.push(line.h[i]);
      v.sort((a, b) => a - b);
      return v;
    };
    const ground = near([1]);
    const top = near([3]);
    const gm = ground.length ? ground[Math.floor(ground.length / 2)] : null;
    const tmax = top.length ? top[Math.floor(top.length * 0.98)] : null;
    const parts = [
      `<b>${(this.pos / 1000).toFixed(3)} km</b> along track`,
      `${lat.toFixed(5)}°N, ${Math.abs(lon).toFixed(5)}°W`,
      gm != null ? `ground ≈ ${gm.toFixed(1)} m` : "no ground photons here",
      tmax != null && gm != null ? `canopy top ≈ ${(tmax - gm).toFixed(1)} m above ground` : "",
    ].filter(Boolean);
    this.root.querySelector(".is2-readout").innerHTML = `${parts.join(" · ")} <span class="muted">(within ±${NEAR_M} m)</span>`;
  }
}

function niceTicks(lo, hi, n) {
  const raw = (hi - lo) / n;
  const exp = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((k) => k * exp).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return { ticks, decimals: Math.max(0, -Math.floor(Math.log10(step) + 1e-9)) };
}
