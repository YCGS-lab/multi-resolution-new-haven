// Benchmarks the website's map rendering in headless Chromium.
//
//   node bench.mjs [--runs 5] [--latency 40] [--out results.json] [--products a/b,c/d] [--only REGEX] NAME=URL ...
//
// e.g. node bench.mjs before=http://localhost:8001/website/ after=http://localhost:8000/website/
//
// Each URL is a copy of website/ (same catalog.json and image-data/). For each
// scenario and site, a fresh browser context opens the page and the script
// drives it through window.app (see main.js), timing until the maps settle:
// no tile requests pending and every deck.gl layer loaded, for 300 ms.
//
// Scenarios (COG products, --products; see fixtures.py for the fixture products):
//   load:<product>   cold page load of the viewer at the full extent
//   zoom:<product>   then four zoom-ins by 2x, settling after each
//   pan:<product>    then a 3 s drag across the map at that zoom (frame times)
//   switch           stepping through five Landsat products (one shared COG)
//   grid             a 2 x 2 grid of four COG products
//   payload          JavaScript and wasm loaded by the page (bytes, gzipped bytes)
//
// Reported per run: wall time to settle, bytes and count of requests to
// image-data/ (the COGs), main-thread long tasks (> 50 ms, total blocking
// time), and for pan the frame-time distribution. `--latency` adds that many
// ms of round-trip latency to every request (Chrome DevTools throttling),
// a rough stand-in for a CDN.

import { writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { chromium } from "playwright";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args.splice(i, 2)[1] : dflt;
};
const RUNS = +opt("runs", 5);
const LATENCY = +opt("latency", 0);
const OUT = opt("out", null);
const ONLY = opt("only", null); // regular expression of scenario labels to run
const CHROME = opt("chrome", process.env.CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome");
const PRODUCTS = opt("products", "landsat/truecolor,ct-impervious-2023/classes,fixtures/jpeg,fixtures/dem,fixtures/tracks").split(",");
const sites = args.map((a) => a.split("=", 2));
if (!sites.length) throw new Error("usage: node bench.mjs [--runs N] [--latency MS] NAME=URL ...");

const SWITCH = ["landsat/truecolor", "landsat/cir", "landsat/veg", "landsat/urban", "landsat/lst"];
const GRID = ["landsat/truecolor", "fixtures/jpeg", "fixtures/dem", "prism/tmean"];

// In-page helpers, installed before the app's scripts run.
function instrument() {
  window.__bench = { longTasks: [], t0: performance.now() };
  new PerformanceObserver((l) => window.__bench.longTasks.push(...l.getEntries().map((e) => e.duration))).observe({
    type: "longtask",
    buffered: true,
  });
  // Count tile requests: patch LoadingState (mapview.js) when main.js sets
  // window.app, before any tile is requested.
  window.__started = 0;
  let app;
  Object.defineProperty(window, "app", {
    configurable: true,
    get: () => app,
    set(v) {
      app = v;
      const proto = Object.getPrototypeOf(v.viewer.loading);
      const start = proto.start;
      proto.start = function () {
        window.__started++;
        return start.call(this);
      };
    },
  });
  window.__states = () => {
    const app = window.app;
    if (!app) return [];
    if (app.grid.active) return app.grid.slots.filter((s) => s.sel && s.loading).map((s) => s.loading);
    return [app.viewer.loading];
  };
  window.__deckLoaded = () => {
    const app = window.app;
    const deck = app.grid.active ? app.grid.deck : app.viewer.deck;
    const lm = deck.layerManager;
    return !!lm && lm.getLayers().every((l) => l.isLoaded);
  };
  window.__cogBytes = () => {
    const rs = performance.getEntriesByType("resource").filter((r) => r.name.includes("/image-data/"));
    return { requests: rs.length, bytes: rs.reduce((s, r) => s + (r.transferSize || r.encodedBodySize || 0), 0) };
  };
}

/**
 * Wait until every map is settled, after at least `minStarted` tile requests
 * (counted from page load if `fromLoad`, else from now).
 */
async function settle(page, { minStarted = 1, fromLoad = false, timeout = 120000 } = {}) {
  await page.waitForFunction(() => window.app, null, { timeout });
  return page.evaluate(
    async ({ minStarted, fromLoad, timeout }) => {
      const t0 = performance.now();
      const base = fromLoad ? 0 : window.__started;
      let stableSince = null;
      for (;;) {
        await new Promise((r) => setTimeout(r, 25));
        const started = window.__started - base;
        const idle = started >= minStarted && window.__states().every((s) => s.pending === 0) && window.__deckLoaded();
        const now = performance.now();
        if (!idle) stableSince = null;
        else if (stableSince === null) stableSince = now;
        else if (now - stableSince >= 300) return { ms: stableSince - t0, at: stableSince, started };
        if (now - t0 > timeout) return { ms: NaN, at: NaN, started, timeout: true };
      }
    },
    { minStarted, fromLoad, timeout },
  );
}

async function snapshot(page) {
  return page.evaluate(() => ({ ...window.__cogBytes(), longTasks: window.__bench.longTasks.slice(), t: performance.now() }));
}

function delta(a, b) {
  const lt = b.longTasks.slice(a.longTasks.length);
  return {
    cogRequests: b.requests - a.requests,
    cogBytes: b.bytes - a.bytes,
    longTasks: lt.length,
    blockingMs: lt.reduce((s, d) => s + Math.max(0, d - 50), 0),
  };
}

async function newPage(browser) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (e) => console.error(`  [pageerror] ${e.message}`));
  await page.addInitScript(instrument);
  if (LATENCY) {
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: LATENCY,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });
  }
  return { context, page };
}

const scenarios = {
  /** Script and wasm bytes the page loads (decoded, and gzipped as a CDN would send them). */
  async payload(browser, url) {
    const { context, page } = await newPage(browser);
    const bodies = [];
    page.on("response", (r) => {
      if (/\.(m?js|wasm)(\?|$)|\/\+esm$/.test(r.url())) bodies.push(r.body().then((b) => [r.url(), b], () => null));
    });
    await page.goto(`${url}#a=${PRODUCTS[0]}`);
    await settle(page, { fromLoad: true });
    // Each URL once (decoder workers each load the worker script and wasm).
    const files = [...new Map((await Promise.all(bodies)).filter(Boolean)).entries()];
    await context.close();
    return {
      files: files.length,
      bytes: files.reduce((n, [, b]) => n + b.length, 0),
      gzipBytes: files.reduce((n, [, b]) => n + gzipSync(b).length, 0),
    };
  },

  async load(browser, url, product) {
    const { context, page } = await newPage(browser);
    await page.goto(`${url}#a=${product}`);
    const s = await settle(page, { fromLoad: true });
    const snap = await snapshot(page);
    await context.close();
    // settleMs: from navigation start (the page's time origin)
    return { settleMs: s.at, ...delta({ requests: 0, bytes: 0, longTasks: [] }, snap) };
  },

  async zoom(browser, url, product) {
    const { context, page } = await newPage(browser);
    await page.goto(`${url}#a=${product}`);
    await settle(page, { fromLoad: true });
    const a = await snapshot(page);
    let ms = 0;
    for (let i = 0; i < 4; i++) {
      await page.evaluate(() => window.app.viewer.zoomBy(1));
      const s = await settle(page, { minStarted: 0 }); // past the finest overview, no new tiles
      ms += s.ms;
    }
    const r = { settleMs: ms, ...delta(a, await snapshot(page)) };
    await context.close();
    return r;
  },

  async pan(browser, url, product) {
    const { context, page } = await newPage(browser);
    await page.goto(`${url}#a=${product}`);
    await settle(page, { fromLoad: true });
    await page.evaluate(() => window.app.viewer.zoomBy(3));
    await settle(page, { minStarted: 0 });
    const a = await snapshot(page);
    const box = await page.locator("#viewer-map").boundingBox();
    await page.evaluate(() => {
      const f = (window.__frames = []);
      let last = performance.now();
      const tick = (t) => {
        f.push(t - last);
        last = t;
        if (!window.__stopFrames) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    const [x0, y0] = [box.x + box.width * 0.8, box.y + box.height * 0.5];
    await page.mouse.move(x0, y0);
    await page.mouse.down();
    const steps = 90;
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(x0 - (box.width * 0.6 * i) / steps, y0 - (box.height * 0.2 * i) / steps);
      await page.waitForTimeout(33);
    }
    await page.mouse.up();
    const frames = await page.evaluate(() => {
      window.__stopFrames = true;
      return window.__frames.slice(1);
    });
    const s = await settle(page, { minStarted: 0 });
    frames.sort((p, q) => p - q);
    const q = (p) => frames[Math.min(frames.length - 1, Math.floor(p * frames.length))];
    const r = {
      settleMs: s.ms,
      frames: frames.length,
      frameP50: q(0.5),
      frameP95: q(0.95),
      frameMax: frames.at(-1),
      ...delta(a, await snapshot(page)),
    };
    await context.close();
    return r;
  },

  async switch(browser, url) {
    const { context, page } = await newPage(browser);
    await page.goto(`${url}#a=${SWITCH[0]}`);
    await settle(page, { fromLoad: true });
    const a = await snapshot(page);
    let ms = 0;
    for (const p of SWITCH.slice(1)) {
      await page.evaluate((p) => window.app.viewer.select("a", p), p);
      ms += (await settle(page, { minStarted: 0 })).ms;
    }
    const r = { settleMs: ms, ...delta(a, await snapshot(page)) };
    await context.close();
    return r;
  },

  async grid(browser, url) {
    const { context, page } = await newPage(browser);
    await page.goto(`${url}#tab=grid&cols=2&g=${GRID.join("|")}`);
    const s = await settle(page, { minStarted: 4, fromLoad: true });
    const r = { settleMs: s.at, ...delta({ requests: 0, bytes: 0, longTasks: [] }, await snapshot(page)) };
    await context.close();
    return r;
  },
};

const median = (xs) => {
  const v = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : NaN;
};

const launch = () =>
  chromium.launch({
    executablePath: CHROME,
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  });
const jobs = [
  ["payload", "payload"],
  ...PRODUCTS.flatMap((p) => ["load", "zoom", "pan"].map((s) => [`${s}:${p}`, s, p])),
  ["switch", "switch"],
  ["grid", "grid"],
];
const results = {};
for (const [label, scenario, product] of jobs.filter(([label]) => !ONLY || new RegExp(ONLY).test(label))) {
  results[label] = {};
  for (const [name, url] of sites) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) {
      const browser = await launch(); // a fresh browser per run: no shared caches
      try {
        runs.push(await scenarios[scenario](browser, url, product));
      } finally {
        await browser.close();
      }
    }
    const summary = Object.fromEntries(Object.keys(runs[0]).map((k) => [k, median(runs.map((r) => r[k]))]));
    results[label][name] = { median: summary, runs };
    console.log(`${label.padEnd(26)} ${name.padEnd(8)} ${JSON.stringify(summary)}`);
  }
}
if (OUT) writeFileSync(OUT, `${JSON.stringify({ runs: RUNS, latency: LATENCY, sites: Object.fromEntries(sites), results }, null, 1)}\n`);
