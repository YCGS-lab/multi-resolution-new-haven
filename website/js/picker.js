// Hierarchical image picker: a button that opens a searchable, collapsible
// tree of groups -> products. Products that need an API key the user has not
// entered (lock) or the cloud deployment (cloud) are grayed out, with the
// reason as a tooltip; picking a locked one opens the credentials dialog.
// Products with no data in the map's view (coverage) are dimmed too, as a
// hint only: they can still be picked.

import { openCredentials, requirement } from "./env.js";
import { coverageMiss } from "./slot.js";

const popup = () => document.getElementById("picker-popup");
const collapsed = new Set(); // group paths collapsed by the user (shared by all pickers)
let active = null; // the picker whose popup is open

const REQ_ICON = { credential: "🔒", cloud: "☁", outside: "⌖" };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

export class Picker {
  /**
   * host: element to render the button into.
   * onSelect(id) is called when the user picks an image.
   * view() is the map's lon / lat box [w, s, e, n] (products without data there are dimmed).
   */
  constructor(host, catalog, { onSelect, view, placeholder = "Select an image", compact = false } = {}) {
    this.catalog = catalog;
    this.onSelect = onSelect;
    this.view = view;
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
    const req = requirement(r);
    this.button.innerHTML = `
      <span class="pb-text">
        <span class="pb-path">${esc(path)}</span>
        <span class="pb-label">${req.ok ? "" : `<span class="req-icon ${req.kind}" aria-hidden="true">${REQ_ICON[req.kind]}</span>`}${esc(r.label)}</span>
      </span>
      <span class="caret">▾</span>`;
    this.button.title = `${path} › ${r.label}${req.ok ? "" : `\n${req.message}`}`;
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

  // #region picker-tree
  renderTree(query) {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = (item) => {
      const hay = [...item.path, item.label, item.title, item.menu_title, item.id].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    };
    const cur = this.catalog.get(this.sel);
    const view = this.view?.();
    const html = [];
    // Returns NONE (nothing shown), SHOWN, or OUT (shown, but no data in view).
    const NONE = 0,
      SHOWN = 1,
      OUT = 2;
    const walk = (node, depth, path) => {
      if (node.layers) {
        if (!matches(node)) return NONE;
        const isCur = cur === node;
        const req = requirement(node);
        const out = coverageMiss(node, view);
        const kind = !req.ok ? req.kind : out ? "outside" : null;
        const icon = kind ? `<span class="req-icon ${kind}" aria-hidden="true">${REQ_ICON[kind]}</span>` : "";
        const tip = !req.ok ? req.message : out ? `No data in view: covers ${node.coverage.name}` : node.title || node.menu_title;
        html.push(`
          <div class="pk-item${isCur ? " current" : ""}${req.ok ? "" : ` unavailable ${req.kind}`}${out ? " outside" : ""}" style="--depth:${depth}">
            <button type="button" class="pk-pick" data-id="${esc(node.id)}" role="option" aria-selected="${isCur}"
              ${req.ok ? "" : `aria-disabled="true" data-req="${req.kind}" data-cred="${esc(req.credential ?? "")}"`}
              title="${esc(tip)}">${icon}${esc(node.label)}</button>
          </div>`);
        return out ? OUT : SHOWN;
      }
      const key = [...path, node.label].join("/");
      const start = html.length;
      html.push(""); // placeholder for the group header
      const isCollapsed = !words.length && collapsed.has(key);
      const childStart = html.length;
      const shown = node.children.map((c) => walk(c, depth + 1, [...path, node.label])).filter((r) => r !== NONE);
      if (!shown.length) {
        html.length = start;
        return NONE;
      }
      const out = shown.every((r) => r === OUT);
      if (isCollapsed) html.length = childStart;
      html[start] = `
        <button type="button" class="pk-group${out ? " outside" : ""}" style="--depth:${depth}" data-key="${esc(key)}" aria-expanded="${!isCollapsed}"
          ${out ? `title="No data in view"` : ""}>
          <span class="pk-caret">${isCollapsed ? "▸" : "▾"}</span>${esc(node.label)}
        </button>`;
      return out ? OUT : SHOWN;
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
    tree.querySelectorAll(".pk-pick").forEach((b) =>
      b.addEventListener("click", () => {
        if (b.dataset.req === "credential") {
          close();
          openCredentials(b.dataset.cred);
        } else if (!b.dataset.req) pick(b.dataset.id);
      }),
    );
  }
  // #endregion picker-tree
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
