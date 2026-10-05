// The image catalog (catalog.json, written by scripts/website/build_catalog.py).
//
// World coordinates used by every map: EPSG:3857 meters relative to the center
// of the extent view ("greater"), with y up. Images are placed by their
// EPSG:3857 bounds, so figures of either view line up.

const R = 6378137; // Web Mercator sphere radius (m)

export async function loadCatalog(url = "catalog.json") {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
  return new Catalog(await res.json());
}

export class Catalog {
  constructor(data) {
    this.data = data;
    this.views = data.views;
    const b = data.views[data.extent].bounds;
    this.origin = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
    this.extent = this.worldBounds(b);
    this.extentTitle = data.views[data.extent].title;
    this.tree = data.tree;
    this.items = new Map(); // id -> item (with .path: ancestor labels, .parent: group)
    this.order = []; // item ids, menu order
    const walk = (node, path, parent) => {
      if (node.images) {
        node.path = path;
        node.parent = parent;
        this.items.set(node.id, node);
        this.order.push(node.id);
      } else {
        for (const c of node.children) walk(c, [...path, node.label], node);
      }
    };
    for (const n of this.tree) walk(n, [], null);
    this.landmarks = data.landmarks.map((l) => ({ ...l, position: this.lonLatToWorld(l.lon, l.lat) }));
  }

  get isEmpty() {
    return this.order.length === 0;
  }

  /** EPSG:3857 [xmin, ymin, xmax, ymax] -> world [left, bottom, right, top]. */
  worldBounds(b) {
    const [ox, oy] = this.origin;
    return [b[0] - ox, b[1] - oy, b[2] - ox, b[3] - oy];
  }

  lonLatToWorld(lon, lat) {
    const x = (R * lon * Math.PI) / 180;
    const y = R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
    return [x - this.origin[0], y - this.origin[1]];
  }

  worldToLon(x) {
    return (((x + this.origin[0]) / R) * 180) / Math.PI;
  }

  worldToLat(y) {
    return ((2 * Math.atan(Math.exp((y + this.origin[1]) / R)) - Math.PI / 2) * 180) / Math.PI;
  }

  latToWorldY(lat) {
    return this.lonLatToWorld(0, lat)[1];
  }

  /** Ground meters per world (Web Mercator) meter at a world y. */
  groundScale(y) {
    return Math.cos((this.worldToLat(y) * Math.PI) / 180);
  }

  viewNames(item) {
    return Object.keys(this.views).filter((v) => item.images[v]);
  }

  /** Resolve a selection {id, view} to {item, view, meta}, or null. */
  resolve(sel) {
    if (!sel) return null;
    const item = this.items.get(sel.id);
    if (!item) return null;
    const view = item.images[sel.view] ? sel.view : this.viewNames(item)[0];
    const meta = item.images[view];
    return { item, view, meta, bounds: this.worldBounds(meta.bounds) };
  }

  /** Selection for an item, keeping `view` when the item has it. */
  select(id, view) {
    const item = this.items.get(id);
    if (!item) return null;
    return { id, view: item.images[view] ? view : this.viewNames(item)[0] };
  }

  /** The item `step` places away from `id` among its siblings in the menu (wrapping). */
  sibling(id, step) {
    const item = this.items.get(id);
    const sibs = item.parent ? item.parent.children.filter((c) => c.images) : this.order.map((i) => this.items.get(i));
    const i = sibs.indexOf(item);
    return sibs[(i + step + sibs.length) % sibs.length].id;
  }

  /** Title for a resolved selection: sidecar title, else the menu's fallback. */
  title(r) {
    return r.meta.title || r.item.title;
  }
}

// Image cache: one decode per file, shared by all maps.
const images = new Map();

export function loadImage(src) {
  if (!images.has(src)) {
    const p = new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`could not load ${src}`));
      img.src = src;
    });
    images.set(src, p);
    p.catch(() => images.delete(src));
  }
  return images.get(src);
}
