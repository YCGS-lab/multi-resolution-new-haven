import { loadCatalog } from "./catalog.js";
import { Grid } from "./grid.js";
import { isOpen } from "./picker.js";
import { Viewer } from "./viewer.js";

const settings = { labels: true };

// Selections in the URL hash: "<dataset>/<product>" (an "@<view>" suffix from
// older links is ignored).
const enc = (id) => id ?? "";
const dec = (s, catalog) => (s && catalog.get(s.split("@")[0]) ? s.split("@")[0] : null);

async function main() {
  let catalog;
  try {
    catalog = await loadCatalog();
  } catch (err) {
    return fatal(
      `Could not load <code>catalog.json</code> (${err.message}).`,
      "Build it with <code>uv run scripts/website/build_catalog.py</code>, then serve the repository root with <code>uv run scripts/website/serve.py</code> and open <code>/website/</code>.",
    );
  }
  if (catalog.isEmpty) {
    return fatal(
      "No images in the catalog.",
      "Run the datasets' <code>create-cog.py</code> / <code>website-layers.py</code> scripts, then re-run <code>uv run scripts/website/build_catalog.py</code>.",
    );
  }

  const viewer = new Viewer(document.getElementById("viewer"), catalog, settings);
  const grid = new Grid(document.getElementById("grid"), catalog, settings);
  window.app = { catalog, viewer, grid }; // for debugging from the console

  // ----- restore state from the URL -----------------------------------
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.get("labels") === "0") settings.labels = false;
  document.getElementById("labels-toggle").checked = settings.labels;
  viewer.select("a", dec(params.get("a"), catalog) ?? catalog.order[0]);
  if (params.get("mode")) viewer.setMode(params.get("mode"));
  if (params.get("b")) {
    viewer.select("b", dec(params.get("b"), catalog));
    viewer.setCompare(true);
  }
  if (params.get("g") !== null) {
    grid.restore({
      cols: +params.get("cols") || 2,
      slots: params
        .get("g")
        .split("|")
        .map((s) => dec(s, catalog)),
    });
  }

  // ----- tabs -----------------------------------------------------------
  const tabs = document.querySelectorAll("[role=tab]");
  let tab = "viewer";
  const showTab = (name) => {
    tab = name;
    tabs.forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === name));
    document.getElementById("viewer").hidden = name !== "viewer";
    document.getElementById("grid").hidden = name !== "grid";
    document.body.classList.toggle("grid-active", name === "grid");
    grid.setActive(name === "grid");
    if (name === "viewer") viewer.update();
    saveState();
  };
  tabs.forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

  // ----- labels toggle ------------------------------------------------------
  const setLabels = (on) => {
    settings.labels = on;
    document.getElementById("labels-toggle").checked = on;
    viewer.update();
    grid.update();
    saveState();
  };
  document.getElementById("labels-toggle").addEventListener("change", (e) => setLabels(e.target.checked));

  // ----- keyboard shortcuts -------------------------------------------------
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || isOpen() || e.target.closest("input, select, textarea")) return;
    if (e.key === "l" || e.key === "L") setLabels(!settings.labels);
    else if (tab === "viewer" && e.key === "[") viewer.step("a", -1);
    else if (tab === "viewer" && e.key === "]") viewer.step("a", 1);
    else if (e.key === "0") (tab === "viewer" ? viewer : grid).reset();
    else return;
    e.preventDefault();
  });

  // ----- state -> URL -------------------------------------------------------
  let lastHash = "";
  function saveState() {
    const p = new URLSearchParams();
    if (tab !== "viewer") p.set("tab", tab);
    const v = viewer.state;
    p.set("a", enc(v.a));
    if (v.b) {
      p.set("b", enc(v.b));
      p.set("mode", v.mode);
    }
    const g = grid.state;
    if (g.slots.some(Boolean)) {
      p.set("cols", g.cols);
      p.set("g", g.slots.map(enc).join("|"));
    }
    if (!settings.labels) p.set("labels", "0");
    const hash = p.toString();
    if (hash !== lastHash) {
      lastHash = hash;
      history.replaceState(null, "", `#${hash}`);
    }
  }
  viewer.onChange = saveState;
  grid.onChange = saveState;

  showTab(params.get("tab") === "grid" ? "grid" : "viewer");
}

function fatal(message, hint) {
  document.querySelector("main").innerHTML = `<div class="fatal"><p>${message}</p><p>${hint}</p></div>`;
}

main();
