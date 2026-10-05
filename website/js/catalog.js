// The image catalog (catalog.json, written by scripts/website/build_catalog.py).
//
// World coordinates used by every map: EPSG:3857 meters relative to the
// center of the extent (Greater New Haven), with y up. `origin` is that
// center in absolute EPSG:3857 meters.

const R = 6378137; // Web Mercator sphere radius (m)

export async function loadCatalog(url = "catalog.json") {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
  return new Catalog(await res.json());
}

export class Catalog {
  constructor(data) {
    this.data = data;
    this.sources = data.sources;
    const b = data.extent.bounds;
    this.origin = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
    this.extent = this.worldBounds(b);
    this.extentTitle = data.extent.title;
    this.tree = data.tree;
    this.items = new Map(); // id -> product (with .path: ancestor labels, .parent: group)
    this.order = []; // product ids, menu order
    const walk = (node, path, parent) => {
      if (node.layers) {
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

  /** The product with this id, or null. */
  get(id) {
    return (id && this.items.get(id)) || null;
  }

  /** The id `step` places away from `id` among its siblings in the menu (wrapping). */
  sibling(id, step) {
    const item = this.items.get(id);
    const sibs = item.parent ? item.parent.children.filter((c) => c.layers) : this.order.map((i) => this.items.get(i));
    const i = sibs.indexOf(item);
    return sibs[(i + step + sibs.length) % sibs.length].id;
  }

  /** Colorbar of a product: the first layer render spec with a label. */
  colorbar(p) {
    return p.layers.map((l) => l.render).find((r) => r.type === "colormap" && r.label) ?? null;
  }

  /** Attributions of a product's service layers (e.g. a basemap). */
  attributions(p) {
    return [...new Set(p.layers.map((l) => this.sources[l.source]?.attribution).filter(Boolean))];
  }
}
