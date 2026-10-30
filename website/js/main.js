import { Animation } from "./animation.js";
import { loadCatalog } from "./catalog.js";
import { onCogOpened } from "./cog.js";
import { initCredentialsDialog, loadEnv, onCredentialsChange } from "./env.js";
import { Grid } from "./grid.js";
import { fitLatitudeAxis } from "./mapview.js";
import { Icesat2 } from "./icesat2.js";
import { Place, SearchBox, TOOLS, ToolsMenu } from "./location.js";
import { isOpen } from "./picker.js";
import { decodeSel, encodeSel } from "./slot.js";
import { calendarOpen } from "./timecontrol.js";
import { Viewer } from "./viewer.js";

const TABS = ["viewer", "grid", "animation", "icesat2"]; // the last are location-specific tools (location.js TOOLS)

// Selections in the URL hash: "<dataset>/<product>[@<time>[..<end>]][;option=value...]"
// (see slot.js; an "@<view>" suffix from older links is ignored).

async function main() {
  await loadEnv();
  initCredentialsDialog();
  let catalog;
  try {
    catalog = await loadCatalog();
  } catch (err) {
    return fatal(
      `Could not load <code>catalog.json</code> (${err.message}).`,
      "Build it with <code>uv run scripts/website/build_catalog.py</code>, then serve it with <code>just serve</code> (Caddy) and open <code>http://localhost:8000/</code>.",
    );
  }
  if (catalog.isEmpty) {
    return fatal(
      "No images in the catalog.",
      "Run the datasets' <code>create-cog.py</code> / <code>website-layers.py</code> scripts, then re-run <code>uv run scripts/website/build_catalog.py</code>.",
    );
  }

  // The selected place, from the URL (before the maps, which start there).
  const params = new URLSearchParams(location.hash.slice(1));
  const place = new Place(catalog);
  place.current = place.decode(params.get("loc"));

  fitLatitudeAxis();
  const viewer = new Viewer(document.getElementById("viewer"), catalog, place);
  const grid = new Grid(document.getElementById("grid"), catalog, place);
  const animation = new Animation(document.getElementById("animation"), catalog, place);
  const icesat2 = new Icesat2(document.getElementById("icesat2"), catalog);
  window.app = { catalog, place, viewer, grid, animation, icesat2 }; // for debugging from the console
  // #region cog-opened
  // COG layers join the maps once their headers are read.
  onCogOpened(() => {
    viewer.update();
    grid.update();
    animation.update();
  });
  // Entering or clearing an API key unlocks / locks datasets everywhere.
  onCredentialsChange(() => {
    for (const k of ["a", "b"]) viewer.slots[k].refresh(0), viewer.slotChanged(k);
    for (const s of grid.slots) s.ts.refresh(0), grid.renderSlot(s);
    grid.update();
    animation.refresh();
  });
  // #endregion cog-opened

  // #region url-restore
  // ----- restore state from the URL -----------------------------------
  const a = decodeSel(catalog, params.get("a"));
  if (!a.id) Object.assign(a, decodeSel(catalog, defaultImage(catalog)));
  viewer.setSel("a", a);
  if (params.get("mode")) viewer.setMode(params.get("mode"));
  if (params.get("b")) {
    viewer.setSel("b", decodeSel(catalog, params.get("b")));
    viewer.setCompare(true);
  }
  if (params.get("g") !== null) {
    grid.restore({
      cols: +params.get("cols") || 2,
      slots: params
        .get("g")
        .split("|")
        .map((s) => decodeSel(catalog, s)),
    });
  }
  if (params.get("anim")) animation.restore(params.get("anim"), params.get("from"), params.get("to"));
  if (params.get("beam")) icesat2.restore(params.get("beam"));
  // #endregion url-restore

  // ----- tabs -----------------------------------------------------------
  const tabs = document.querySelectorAll("[role=tab]");
  let tab = "viewer";
  const showTab = (name, { carry = true } = {}) => {
    // The image travels between the viewer and the animation, with its date / the frame shown, and the
    // map's center and zoom.
    if (carry && tab === "viewer" && name === "animation") {
      animation.matchView(viewer.viewState);
      animation.adopt(viewer.slots.a.sel);
    }
    if (carry && tab === "animation" && name === "viewer") {
      const sel = animation.handoff(viewer.slots.a.sel);
      if (sel) viewer.setSel("a", sel);
      viewer.matchView(animation.viewState);
    }
    tab = name;
    tabs.forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === name));
    tools.render();
    for (const t of TABS) document.getElementById(t).hidden = name !== t;
    document.body.classList.toggle("grid-active", name === "grid");
    grid.setActive(name === "grid");
    animation.setActive(name === "animation");
    icesat2.setActive(name === "icesat2");
    if (name === "viewer") viewer.update();
    saveState();
  };
  tabs.forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

  // ----- place search and location-specific tools -----------------------------
  const isTool = (name) => TOOLS.some((t) => t.id === name);
  const tools = new ToolsMenu(document.getElementById("tools-menu"), place, {
    open: (id) => showTab(id),
    active: () => (isTool(tab) ? tab : null),
  });
  // Suggestions are biased towards the center of the map in view.
  const centerOf = (b) => b && [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
  new SearchBox(document.getElementById("place-search"), place, {
    near: () => centerOf(tab === "grid" ? grid.bounds : tab === "animation" ? animation.bounds : viewer.bounds),
  });
  // A new place: every map goes there; a tool not made for it closes.
  place.onChange(() => {
    viewer.reset();
    grid.reset();
    animation.reset();
    if (isTool(tab) && !tools.toolsFor(place.current).some((t) => t.id === tab)) showTab("viewer");
    saveState();
  });

  // #region keyboard
  // ----- keyboard shortcuts -------------------------------------------------
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || isOpen() || calendarOpen() || e.target.closest("input, select, textarea, dialog")) return;
    if (tab === "viewer" && e.key === "[") viewer.step("a", -1);
    else if (tab === "viewer" && e.key === "]") viewer.step("a", 1);
    else if (tab === "viewer" && e.key === ",") viewer.stepTime("a", -1);
    else if (tab === "viewer" && e.key === ".") viewer.stepTime("a", 1);
    else if (tab === "animation" && e.key === " ") animation.togglePlay();
    else if (tab === "animation" && e.key === "ArrowLeft") animation.stepFrame(-1);
    else if (tab === "animation" && e.key === "ArrowRight") animation.stepFrame(1);
    else if (e.key === "0" && (tab === "viewer" || tab === "grid")) (tab === "viewer" ? viewer : grid).reset();
    else return;
    e.preventDefault();
  });
  // #endregion keyboard

  // #region url-save
  // ----- state -> URL -------------------------------------------------------
  let lastHash = "";
  function saveState() {
    const p = new URLSearchParams();
    if (tab !== "viewer") p.set("tab", tab);
    const v = viewer.state;
    p.set("a", encodeSel(catalog, v.a));
    if (v.b) {
      p.set("b", encodeSel(catalog, v.b));
      p.set("mode", v.mode);
    }
    const g = grid.state;
    if (g.slots.some((s) => s?.id)) {
      p.set("cols", g.cols);
      p.set("g", g.slots.map((s) => encodeSel(catalog, s)).join("|"));
    }
    const an = animation.state;
    if (an.id) {
      p.set("anim", an.id);
      if (an.from) p.set("from", an.from);
      if (an.to) p.set("to", an.to);
    }
    if (icesat2.state) p.set("beam", icesat2.state);
    if (place.current?.id !== "new-haven") p.set("loc", place.encode());
    const hash = p.toString();
    if (hash !== lastHash) {
      lastHash = hash;
      history.replaceState(null, "", `#${hash}`);
    }
  }
  viewer.onChange = saveState;
  grid.onChange = saveState;
  animation.onChange = saveState;
  icesat2.onChange = saveState;
  // #endregion url-save

  showTab(TABS.includes(params.get("tab")) ? params.get("tab") : "viewer", { carry: false });
}

/** First image shown: Landsat true color (live, no key needed) if built, else the first in the menu. */
function defaultImage(catalog) {
  return catalog.get("landsat/truecolor") ? "landsat/truecolor" : catalog.order[0];
}

function fatal(message, hint) {
  document.querySelector("main").innerHTML = `<div class="fatal"><p>${message}</p><p>${hint}</p></div>`;
}

main();
