// Hierarchical image picker: a button that opens a searchable, collapsible
// tree of groups -> products.

const popup = () => document.getElementById("picker-popup");
const collapsed = new Set(); // group paths collapsed by the user (shared by all pickers)
let active = null; // the picker whose popup is open

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

export class Picker {
  /**
   * host: element to render the button into.
   * onSelect(id) is called when the user picks an image.
   */
  constructor(host, catalog, { onSelect, placeholder = "Select an image", compact = false } = {}) {
    this.catalog = catalog;
    this.onSelect = onSelect;
    this.placeholder = placeholder;
    this.sel = null;
    this.button = document.createElement("button");
    this.button.className = "picker-button" + (compact ? " compact" : "");
    this.button.type = "button";
    this.button.setAttribute("aria-haspopup", "listbox");
    this.button.addEventListener("click", () => (active === this ? close() : this.open()));
    host.append(this.button);
    this.render();
  }

  set(sel) {
    this.sel = sel;
    this.render();
  }

  render() {
    const r = this.catalog.get(this.sel);
    if (!r) {
      this.button.innerHTML = `<span class="pb-label placeholder">${esc(this.placeholder)}</span><span class="caret">▾</span>`;
      this.button.title = "";
      return;
    }
    const path = r.path.join(" › ");
    this.button.innerHTML = `
      <span class="pb-text">
        <span class="pb-path">${esc(path)}</span>
        <span class="pb-label">${esc(r.label)}</span>
      </span>
      <span class="caret">▾</span>`;
    this.button.title = `${path} › ${r.label}`;
  }

  open() {
    close();
    active = this;
    this.button.classList.add("open");
    const el = popup();
    el.innerHTML = `
      <input type="search" class="pk-search" placeholder="Search images…" aria-label="Search images" />
      <div class="pk-tree" role="listbox"></div>`;
    el.hidden = false;
    const search = el.querySelector(".pk-search");
    search.addEventListener("input", () => this.renderTree(search.value));
    search.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        el.querySelector(".pk-pick")?.focus();
      } else if (e.key === "Enter") {
        el.querySelector(".pk-pick")?.click();
      }
    });
    this.renderTree("");
    this.position();
    el.querySelector(".pk-item.current")?.scrollIntoView({ block: "center" });
    search.focus({ preventScroll: true });
  }

  position() {
    const el = popup();
    const b = this.button.getBoundingClientRect();
    const width = Math.min(Math.max(b.width, 380), window.innerWidth - 16);
    const left = Math.max(8, Math.min(b.left, window.innerWidth - width - 8));
    const below = window.innerHeight - b.bottom - 12;
    const above = b.top - 12;
    const up = below < 320 && above > below;
    el.style.width = `${width}px`;
    el.style.left = `${left}px`;
    el.style.maxHeight = `${Math.min(560, up ? above : below)}px`;
    el.style.top = up ? "" : `${b.bottom + 4}px`;
    el.style.bottom = up ? `${window.innerHeight - b.top + 4}px` : "";
  }

  renderTree(query) {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = (item) => {
      const hay = [...item.path, item.label, item.title, item.menu_title, item.id].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    };
    const cur = this.catalog.get(this.sel);
    const html = [];
    const walk = (node, depth, path) => {
      if (node.layers) {
        if (!matches(node)) return false;
        const isCur = cur === node;
        html.push(`
          <div class="pk-item${isCur ? " current" : ""}" style="--depth:${depth}">
            <button type="button" class="pk-pick" data-id="${esc(node.id)}" role="option" aria-selected="${isCur}"
              title="${esc(node.title || node.menu_title)}">${esc(node.label)}</button>
          </div>`);
        return true;
      }
      const key = [...path, node.label].join("/");
      const start = html.length;
      html.push(""); // placeholder for the group header
      const isCollapsed = !words.length && collapsed.has(key);
      let any = false;
      const childStart = html.length;
      for (const c of node.children) any = walk(c, depth + 1, [...path, node.label]) || any;
      if (!any) {
        html.length = start;
        return false;
      }
      if (isCollapsed) html.length = childStart;
      html[start] = `
        <button type="button" class="pk-group" style="--depth:${depth}" data-key="${esc(key)}" aria-expanded="${!isCollapsed}">
          <span class="pk-caret">${isCollapsed ? "▸" : "▾"}</span>${esc(node.label)}
        </button>`;
      return true;
    };
    for (const n of this.catalog.tree) walk(n, 0, []);
    const tree = popup().querySelector(".pk-tree");
    tree.innerHTML = html.join("") || `<div class="pk-empty">No images match “${esc(query)}”.</div>`;

    tree.querySelectorAll(".pk-group").forEach((g) =>
      g.addEventListener("click", () => {
        const k = g.dataset.key;
        collapsed.has(k) ? collapsed.delete(k) : collapsed.add(k);
        this.renderTree(popup().querySelector(".pk-search").value);
      }),
    );
    const pick = (id) => {
      close();
      this.set(id);
      this.onSelect?.(id);
    };
    tree.querySelectorAll(".pk-pick").forEach((b) => b.addEventListener("click", () => pick(b.dataset.id)));
  }
}

export function close() {
  if (!active) return;
  active.button.classList.remove("open");
  active.button.focus({ preventScroll: true });
  active = null;
  const el = popup();
  el.hidden = true;
  el.innerHTML = "";
}

export function isOpen() {
  return !!active;
}

// Close on outside click, Escape, resize; arrow keys move between items.
document.addEventListener("pointerdown", (e) => {
  if (active && !popup().contains(e.target) && !active.button.contains(e.target)) close();
});
document.addEventListener("keydown", (e) => {
  if (!active) return;
  if (e.key === "Escape") {
    e.preventDefault();
    close();
  } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && popup().contains(document.activeElement)) {
    const items = [...popup().querySelectorAll(".pk-pick, .pk-group")];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = items[i + (e.key === "ArrowDown" ? 1 : -1)];
    if (next) next.focus();
    else if (e.key === "ArrowUp") popup().querySelector(".pk-search").focus();
  }
});
window.addEventListener("resize", close);
window.addEventListener("scroll", () => active?.position());
