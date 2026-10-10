# Fixtures and benchmark

`scripts/website/benchmark/` checks the website's COG renderer without
credentials, and compares two versions of the site.

## Fixtures

`fixtures.py` writes COGs that exercise every render path the real datasets
use, from sources that need no credentials (NAIP, 3DEP, synthetic points):

| Product | Exercises | Stands in for |
|---|---|---|
| `fixtures/jpeg` | 8-bit JPEG COG, band-interleaved, `identity` | Planet |
| `fixtures/dem` | float LERC, 2 bands, `colormap` + stored-hillshade `shade` | ASTER |
| `fixtures/dem_log` | log color scale, gamma, `extend="min"` | VIIRS night lights |
| `fixtures/classes` | uint8 DEFLATE, `categorical` | CT impervious surface |
| `fixtures/tracks` | sparse points, `dilate_px`, over a desaturated basemap | ICESat-2 |
| `fixtures/expr` | `rgb` with band expressions (`log10`, `max`, ratios) | NISAR |

::: code-group
<<< @/../scripts/website/benchmark/fixtures.py#sparse-tracks [scripts/website/benchmark/fixtures.py#sparse-tracks]
:::

The fixtures appear in the menu under "Other" once built (and would be
deployed with the site; see [Issues and improvements](/issues#fixtures-in-catalog)):

```sh
uv run scripts/website/benchmark/fixtures.py
uv run scripts/website/build_catalog.py
```

## Benchmark

`bench.mjs` drives the site in headless Chromium with Playwright. It
compares two or more copies of the site (`before=URL after=URL`) that
serve the same `catalog.json` and `image-data/`.

```sh
cd scripts/website/benchmark && npm ci
node bench.mjs --runs 3 --out local.json before=http://localhost:8001/website/ after=http://localhost:8000/website/
node bench.mjs --runs 3 --latency 40 --out latency40.json before=... after=...
node report.mjs local.json latency40.json      # Markdown tables
```

| Scenario | Measures |
|---|---|
| `payload` | JavaScript and wasm downloaded, raw and gzipped |
| `load:<product>` | page load to a finished map, full extent |
| `zoom:<product>` | four 2× zoom-ins, each until settled |
| `pan:<product>` | a 3 s drag at 8×: frame times |
| `switch` | stepping through five Landsat products on one COG |
| `grid` | a 2 × 2 grid of four COG products |

Each run uses a fresh browser, so nothing is cached between runs. Reported:
time to settle, the number and bytes of requests to `image-data/`,
main-thread long tasks (> 50 ms) and total blocking time, frame times for
`pan`, medians of the runs. `--latency` adds a fixed delay per request
through Chrome DevTools, as a rough stand-in for a CDN.

### Instrumenting the page <Badge type="warning" text="decision" />

::: code-group
<<< @/../scripts/website/benchmark/bench.mjs#instrument{js} [scripts/website/benchmark/bench.mjs#instrument]
<<< @/../scripts/website/benchmark/bench.mjs#settle{js} [scripts/website/benchmark/bench.mjs#settle]
:::

::: warning How "settled" is detected
A map is settled when no tile request is pending, every deck.gl layer
reports `isLoaded`, and both hold for 300 ms. To count requests from the
very first, the script patches the `LoadingState` prototype at the moment
`main.js` assigns `window.app`, before any tile is requested.

After a zoom or pan no new request may be needed (beyond a COG's finest
overview, tiles are scaled up), so those scenarios wait only for the quiet
period. Page loads also require at least one request to have started.

The benchmark drives the page through `window.app`, the debugging handle
`main.js` exposes. It works on both versions because their Viewer and Grid
classes have the same interface.
:::

::: danger No GPU in the test environment
In a container without a GPU, Chromium renders WebGL in software
(SwiftShader), and per-pixel GPU work becomes far more expensive than on
real hardware. Frame times are an upper bound. Re-run on a machine with a
GPU (`CHROME=/path/to/chrome`) before drawing conclusions about frame rates.
:::

Results of the migration's runs, with every run's numbers:
[benchmarks/2026-10-10](/benchmarks/2026-10-10), summarized in
[Performance](/comparison/performance).
