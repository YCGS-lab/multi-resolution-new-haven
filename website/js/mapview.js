// Pieces shared by the viewer and the grid: deck.gl layers for an image and
// its landmarks, pan/zoom limits, and the HTML around a map (axes, scale bar,
// title block, colorbar / legend).

const { BitmapLayer, ScatterplotLayer, TextLayer, SolidPolygonLayer, PathLayer } = deck;

// Deepest zoom: 2^4 = 16 screen pixels per Web Mercator meter, i.e. ~12 px per
// 1 m pixel of the central view.
export const MAX_ZOOM = 4;
const NODATA_FILL = [208, 208, 208]; // same gray as NODATA_FACE in render.py

/** Zoom at which the whole extent just fits in a w x h px map. */
export function fitZoom(extent, w, h) {
  return Math.log2(Math.min(w / (extent[2] - extent[0]), h / (extent[3] - extent[1])));
}

/** Initial view state: the whole extent. */
export function homeViewState(extent, w, h) {
  return clampViewState({ target: [(extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2, 0], zoom: -Infinity }, extent, w, h);
}

/**
 * Keep the map inside the extent: no zooming out past the whole extent, and
 * no panning beyond its edges (centered on an axis where it does not fill the map).
 */
export function clampViewState(vs, extent, w, h) {
  const minZoom = Math.min(fitZoom(extent, w, h), MAX_ZOOM);
  const zoom = Math.min(MAX_ZOOM, Math.max(minZoom, vs.zoom));
  const s = 2 ** zoom;
  const axis = (c, lo, hi, half) => (hi - lo <= 2 * half ? (lo + hi) / 2 : Math.min(hi - half, Math.max(lo + half, c)));
  const x = axis(vs.target[0], extent[0], extent[2], w / 2 / s);
  const y = axis(vs.target[1], extent[1], extent[3], h / 2 / s);
  return { ...vs, target: [x, y, 0], zoom, minZoom, maxZoom: MAX_ZOOM };
}

/** World x/y of a screen point (px from the map's top left). */
export function unproject(vs, w, h, px, py) {
  const s = 2 ** vs.zoom;
  return [vs.target[0] + (px - w / 2) / s, vs.target[1] - (py - h / 2) / s];
}

export function hexToRgba(hex) {
  const h = hex.replace("#", "");
  const n = (i) => parseInt(h.slice(i, i + 2), 16);
  return [n(0), n(2), n(4), h.length >= 8 ? n(6) : 255];
}

const rect = (b) => [
  [b[0], b[1]],
  [b[2], b[1]],
  [b[2], b[3]],
  [b[0], b[3]],
];

/** Gray "no data" background over the whole extent. */
export function backgroundLayer(id, extent) {
  return new SolidPolygonLayer({ id, data: [{ polygon: rect(extent) }], getPolygon: (d) => d.polygon, getFillColor: NODATA_FILL });
}

/**
 * The image, drawn with nearest-neighbour magnification so native pixels stay
 * sharp blocks when zoomed in. `r` is a resolved selection (Catalog.resolve).
 */
export function imageLayers(id, r, image, catalog, props = {}) {
  const layers = [
    new BitmapLayer({
      id,
      image,
      bounds: r.bounds,
      textureParameters: { minFilter: "linear", mipmapFilter: "linear", magFilter: "nearest" },
      ...props,
    }),
  ];
  // Outline images that cover only part of the extent (central view).
  const e = catalog.extent;
  if (r.bounds.some((v, i) => Math.abs(v - e[i]) > 1)) {
    layers.push(
      new PathLayer({
        id: `${id}-outline`,
        data: [{ path: [...rect(r.bounds), rect(r.bounds)[0]] }],
        getPath: (d) => d.path,
        getColor: [60, 60, 60, 200],
        getWidth: 1,
        widthUnits: "pixels",
        ...props,
      }),
    );
  }
  return layers;
}

/** Landmark markers and names, as in render.add_landmarks. */
export function landmarkLayers(id, catalog, color = "#ffffff") {
  const rgba = hexToRgba(color);
  return [
    new ScatterplotLayer({
      id: `${id}-points`,
      data: catalog.landmarks,
      getPosition: (d) => d.position,
      getRadius: 5,
      radiusUnits: "pixels",
      getFillColor: rgba,
      stroked: true,
      getLineColor: [0, 0, 0, 255],
      getLineWidth: 1.5,
      lineWidthUnits: "pixels",
      updateTriggers: { getFillColor: color },
    }),
    new TextLayer({
      id: `${id}-names`,
      data: catalog.landmarks,
      getPosition: (d) => d.position,
      getText: (d) => d.name,
      getSize: 14,
      getColor: rgba,
      getTextAnchor: (d) => (d.label_left ? "end" : "start"),
      getAlignmentBaseline: "bottom",
      getPixelOffset: (d) => (d.label_left ? [-7, -4] : [7, -4]),
      fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
      fontWeight: 700,
      fontSettings: { sdf: true, fontSize: 64, buffer: 8 },
      outlineWidth: 3,
      outlineColor: [0, 0, 0, 255],
      updateTriggers: { getColor: color },
    }),
  ];
}

// --------------------------------------------------------------------------
// Axes and scale bar
// --------------------------------------------------------------------------

const DEGREE_STEPS = [0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1];

function degreeTicks(lo, hi, maxTicks) {
  const step = DEGREE_STEPS.find((s) => (hi - lo) / s <= maxTicks) ?? 1;
  const decimals = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(+v.toFixed(decimals + 2));
  return { ticks, decimals };
}

const fmtLon = (v, d) => `${Math.abs(v).toFixed(d)}°${v < 0 ? "W" : "E"}`;
const fmtLat = (v, d) => `${Math.abs(v).toFixed(d)}°${v < 0 ? "S" : "N"}`;

function niceLength(maxM) {
  const exp = 10 ** Math.floor(Math.log10(maxM));
  return [5, 2, 1].map((m) => m * exp).find((l) => l <= maxM);
}

/**
 * Longitude / latitude axes and the scale bar of one map frame:
 * .axis-left, .axis-bottom and .scalebar elements inside `frame`.
 */
export class MapChrome {
  constructor(frame, catalog, { tickSpacing = [100, 56] } = {}) {
    this.catalog = catalog;
    this.left = frame.querySelector(".axis-left");
    this.bottom = frame.querySelector(".axis-bottom");
    this.scalebar = frame.querySelector(".scalebar");
    this.tickSpacing = tickSpacing;
    this.key = "";
  }

  update(vs, w, h, showLabels) {
    const c = this.catalog;
    const s = 2 ** vs.zoom;
    const [tx, ty] = vs.target;
    const key = [tx, ty, vs.zoom, w, h, showLabels].join();
    if (key === this.key) return;
    this.key = key;

    if (this.bottom) {
      const x0 = tx - w / 2 / s,
        x1 = tx + w / 2 / s;
      const { ticks, decimals } = degreeTicks(c.worldToLon(x0), c.worldToLon(x1), Math.max(2, Math.floor(w / this.tickSpacing[0])));
      const half = 4 + 3.3 * (decimals + 5); // ~half a label's width (px), to skip clipped labels
      this.bottom.innerHTML = ticks
        .map((lon) => [lon, w / 2 + (c.lonLatToWorld(lon, 0)[0] - tx) * s])
        .filter(([, px]) => px >= half && px <= w - half)
        .map(([lon, px]) => `<span class="tick" style="left:${px.toFixed(1)}px">${fmtLon(lon, decimals)}</span>`)
        .join("");
    }
    if (this.left) {
      const y0 = ty - h / 2 / s,
        y1 = ty + h / 2 / s;
      const { ticks, decimals } = degreeTicks(c.worldToLat(y0), c.worldToLat(y1), Math.max(2, Math.floor(h / this.tickSpacing[1])));
      this.left.innerHTML = ticks
        .map((lat) => [lat, h / 2 - (c.latToWorldY(lat) - ty) * s])
        .filter(([, py]) => py >= 7 && py <= h - 7)
        .map(([lat, py]) => `<span class="tick" style="top:${py.toFixed(1)}px">${fmtLat(lat, decimals)}</span>`)
        .join("");
    }
    if (this.scalebar) {
      this.scalebar.hidden = !showLabels;
      if (showLabels) {
        const mPerPx = c.groundScale(ty) / s; // ground meters per screen pixel
        const len = niceLength((w / 5) * mPerPx);
        const label = len >= 1000 ? `${len / 1000} km` : `${len} m`;
        this.scalebar.innerHTML = `<span>${label}</span><div class="bar" style="width:${(len / mPerPx).toFixed(1)}px"></div>`;
      }
    }
  }
}

// --------------------------------------------------------------------------
// Title block and colorbar / legend
// --------------------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

/** Title, subtitle and view line for a resolved selection. */
export function titleHTML(r, catalog, { tag = "", compact = false } = {}) {
  const view = catalog.views[r.view];
  const sub = r.meta.subtitle;
  const viewLine = `${view.title} · ${view.pixel_size_m.toFixed(1)} m/pixel`;
  const link = r.meta.labeled
    ? ` · <a href="${esc(r.meta.labeled)}" target="_blank" rel="noopener" title="Open the matplotlib-labeled figure">labeled PNG</a>`
    : "";
  const subHTML = sub
    ? compact
      ? `<div class="subtitle compact" title="${esc(sub)}">${esc(sub.split("\n")[0])}</div>`
      : `<div class="subtitle">${esc(sub)}</div>`
    : "";
  return `
    <div class="title-row">${tag}<h2 class="title">${esc(catalog.title(r))}</h2></div>
    ${subHTML}
    <div class="view-line">${esc(viewLine)}${link}</div>`;
}

function linearTicks(lo, hi, n = 5) {
  const raw = (hi - lo) / n;
  const exp = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * exp).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9 * step; v += step) ticks.push(v);
  const decimals = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9) + (step / exp === 2.5 ? 1 : 0));
  return ticks.map((v) => [v, v.toFixed(decimals)]);
}

function logTicks(lo, hi) {
  const ticks = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) ticks.push([v, String(+v.toPrecision(3))]);
    }
  return ticks;
}

function colorbarHTML(cb) {
  const log = cb.scale === "log";
  const f = (v) => (log ? Math.log(v / cb.vmin) / Math.log(cb.vmax / cb.vmin) : (v - cb.vmin) / (cb.vmax - cb.vmin));
  const ticks = cb.ticks
    ? cb.ticks.map((v) => [v, String(+v.toPrecision(4))])
    : log
      ? logTicks(cb.vmin, cb.vmax)
      : linearTicks(cb.vmin, cb.vmax);
  const stops = cb.colors.map((c, i) => `${c} ${((i / (cb.colors.length - 1)) * 100).toFixed(2)}%`).join(",");
  const under = ["min", "both"].includes(cb.extend);
  const over = ["max", "both"].includes(cb.extend);
  return `
    <div class="colorbar">
      <div class="cb-label">${esc(cb.label)}</div>
      <div class="cb-bar">
        ${under ? `<span class="cb-ext under" style="background:${cb.under}"></span>` : ""}
        <span class="cb-ramp" style="background:linear-gradient(to right,${stops})"></span>
        ${over ? `<span class="cb-ext over" style="background:${cb.over}"></span>` : ""}
      </div>
      <div class="cb-ticks">${ticks
        .map(([v, label]) => `<span style="left:${(f(v) * 100).toFixed(2)}%">${esc(label)}</span>`)
        .join("")}</div>
    </div>`;
}

function legendHTML(lg) {
  return `
    <div class="legend">
      ${lg.title ? `<div class="lg-title">${esc(lg.title)}</div>` : ""}
      <div class="lg-entries" style="--ncol:${lg.ncol || 1}">${lg.entries
        .map((e) => `<span class="lg-entry"><span class="swatch" style="background:${e.color}"></span>${esc(e.label)}</span>`)
        .join("")}</div>
    </div>`;
}

/** Colorbar or legend, plus the source line. */
export function keyHTML(r, { tag = "", source = true } = {}) {
  const m = r.meta;
  const parts = [];
  if (m.colorbar) parts.push(colorbarHTML(m.colorbar));
  if (m.legend) parts.push(legendHTML(m.legend));
  if (!m.title)
    parts.push(`<div class="no-meta">No colorbar / legend: re-run this dataset's visualize script to write its .json sidecar.</div>`);
  if (source && m.source) parts.push(`<div class="source">Source: ${esc(m.source)}</div>`);
  return parts.length ? `${tag}<div class="key-body">${parts.join("")}</div>` : "";
}
