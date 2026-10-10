# Issues and improvements

This page lists problems and possible improvements found while documenting
the code. They come from reading every file for these docs and from
separate review passes over the viewer, the shared Python code and tooling,
and the dataset scripts. Every entry was checked against the code. Entries
marked **reproduced** were also demonstrated by running the code.

Each entry gives:

- **Severity**: *high* (wrong output or a security exposure in normal use),
  *medium* (wrong output or failure in a plausible case, or a real cost),
  *low* (edge cases, tidiness).
- **Origin**: *migration* if the deck.gl-raster change (this PR) introduced
  it, *earlier* if it was already in commit `bd8e191`.
- **Where**: files and functions rather than line numbers, which drift.

Apart from the first entry, nothing here has been fixed.

## Summary

| # | Issue | Area | Severity | Origin |
|---|---|---|---|---|
| [1](#lut-context) | Colormap layers drawn black in the grid | viewer | high | migration, **fixed** |
| [2](#hillshade-direction) | Hillshades are lit from the southeast, not the northwest | pipeline, viewer | high | earlier |
| [3](#preview-exposes-repo) | `just preview` serves the whole repository, credentials included, to the network | tooling | high | earlier |
| [4](#serve-root) | `serve.py` serves the repository root, not `website/` | tooling | medium | earlier |
| [5](#fixtures-in-catalog) | Benchmark fixtures end up in the menu and in the deployed site | tooling | medium | migration |
| [6](#deploy-delete) | `just deploy` can delete COGs from the bucket, with no versioning to recover them | deploy | medium | earlier |
| [7](#terraform-state) | README, justfile and Terraform disagree about where the state lives | deploy | medium | earlier |
| [8](#texture-leak) | Tile textures are not freed when a COG layer is removed | viewer | medium | migration |
| [9](#spec-edge-cases) | Bad numbers in a render spec hang the tab or break the shader | viewer | medium | both |
| [10](#errors-stop-rendering) | One failing product stops all map updates; failures are silent | viewer | medium | both |
| [11](#loading-counter) | The grid's loading counter goes negative after a product change | viewer | medium | earlier |
| [12](#url-validation) | URL values (`cols`, `mode`) are not validated | viewer | medium | earlier |
| [13](#reloads) | Hidden layers are dropped and reloaded from scratch | viewer | medium | migration (cost) |
| [14](#nisar-rain) | NISAR "driest acquisition" undercounts rain early in the window | datasets | medium | earlier |
| [15](#partial-files) | Interrupted runs leave partial files that later runs treat as done | pipeline | medium | earlier |
| [16](#unpinned-python) | Python dependencies are not pinned | pipeline | medium | earlier |
| [17](#no-tests) | No tests and no CI | all | medium | earlier |
| [18](#perf-followups) | Performance follow-ups from the migration | viewer | medium | migration |
| [19](#planet-gaps) | Missing Planet tiles become black pixels | datasets | low | earlier |
| [20](#stale-facts) | Hard-coded dates and versions will go stale | datasets | low | earlier |
| [21](#duplication) | Duplicated code and constants | all | low | earlier |
| [22](#dead-code) | Dead code and unneeded exports | all | low | both |
| [23](#security-hardening) | Security hardening (CloudFront headers, HTML escaping) | deploy, viewer | low | earlier |
| [24](#accessibility) | Accessibility gaps | viewer | low–medium | earlier |
| [25](#small-bugs) | Smaller bugs | all | low | both |

## Fixed

### 1. Colormap layers drawn black in the grid {#lut-context}

**Severity** high · **Origin** migration · **Status** fixed in this PR,
reproduced before and after

- **Where:** `website/js/cog.js`, `lutTexture()`.
- **Problem:** the lookup texture of a colormap or categorical layer was
  cached once per compiled program. The viewer and the grid each have
  their own `Deck`, so each has its own WebGL context. A texture works only
  in the context that created it. Once a product such as the DEM had been
  shown in the viewer, the grid reused the viewer's texture, and the
  product came out black wherever it had data.
- **Fix:** the cache is now keyed by device first, then by program.
  Showing the DEM fixture in the viewer and then in the grid now gives the
  same image as showing it in the grid alone.

## High

### 2. Hillshades are lit from the southeast {#hillshade-direction}

**Severity** high · **Origin** earlier · **Reproduced**

- **Where:** `scripts/common/render.py`, `hillshade()`. The browser copy is
  `website/js/tiles.js`, `hillshade()`.
- **Problem:** the docstring, the [Figures page](/pipeline/figures#hillshade)
  and the glossary say the sun is in the northwest (azimuth 315°). The
  code computes `aspect = arctan2(-gx, gy)`, where `gy` is the
  row-direction (southward) gradient, and then applies the usual
  `360 − azimuth + 90` conversion. The two conventions do not match. For a
  plane rising to the east (facing west), the function returns 0.15. A
  normal-vector calculation with the sun in the northwest gives 0.85. For a
  slope facing northwest it returns 0, not 0.99. Every slope is shaded as
  if the sun were in the southeast.
- **Effect:** relief can read inverted, with valleys looking like ridges.
  This affects every shaded product: the ASTER, 3DEP and lidar figures,
  the stored hillshade band of the website COGs, and the live ArcGIS
  shading in the browser.
- **Fix:** use the ESRI form `aspect = arctan2(gy, -gx)` (or flip the sign
  of `dy`) in both copies. Add a test on a tilted plane. Then rebuild the
  COGs that store a hillshade band.

### 3. `just preview` serves the whole repository to the network {#preview-exposes-repo}

**Severity** high · **Origin** earlier

- **Where:** `justfile`, `preview`:
  `caddy file-server --browse --listen :8000`.
- **Problem:** this listens on all interfaces, lists directories, and
  serves the repository root. That includes `_credentials.toml` (Planet,
  CDS and AWS keys) and `terraform/aws/terraform.tfstate` (which holds the
  deploy user's secret key) if it exists locally, plus `.git/`. Anyone on
  the same network can read them.
- **Fix:** `caddy file-server --root website --listen 127.0.0.1:8000`, with
  no `--browse`. Or drop the recipe in favor of `serve.py`.

## Medium

### 4. `serve.py` serves the repository root {#serve-root}

**Severity** medium · **Origin** earlier

- **Where:** `scripts/website/serve.py`, `main()` (`directory=str(REPO)`).
- **Problem:** it binds to 127.0.0.1 by default, which limits exposure, but
  `--bind 0.0.0.0` exposes the same files as in [3](#preview-exposes-repo).
  Other local processes and DNS-rebinding pages can also reach them. The
  site needs only `website/`.
- **Fix:** serve `website/`, or refuse paths outside it.

### 5. Benchmark fixtures end up in the menu and the deployed site {#fixtures-in-catalog}

**Severity** medium · **Origin** migration

- **Where:** `scripts/website/benchmark/fixtures.py` writes
  `website/image-data/fixtures-*.tif` and `.json`. `build_catalog.py` puts
  any product not in `TREE` under "Other". `just deploy` syncs all of
  `website/`.
- **Problem:** after a benchmark run, six `fixtures/*` products show in
  the menu ([as documented](/build/benchmark#fixtures)). The next deploy
  uploads about 19 MB of test COGs to the public site.
- **Fix:** write the fixtures to their own directory, served only by the
  benchmark, or have `build_catalog.py` skip `fixtures` unless a flag is
  set. Add `--exclude "image-data/fixtures*"` to the sync as a backstop.

### 6. `just deploy` can delete COGs with no way back {#deploy-delete}

**Severity** medium · **Origin** earlier

- **Where:** `terraform/aws/outputs.tf`, `deploy_commands`
  (`aws s3 sync --delete`). The bucket in `main.tf` has no versioning.
- **Problem:** most datasets need credentials, so a given machine's
  `website/image-data/` is often incomplete. A deploy from such a machine
  deletes the missing COGs from the bucket for good.
- **Fix:** enable bucket versioning with an expiry rule for old versions.
  Have the deploy first check that every COG named in `catalog.json`
  exists locally.

### 7. Terraform state: README, justfile and config disagree {#terraform-state}

**Severity** medium · **Origin** earlier

- **Where:** `terraform/aws/versions.tf` (no `backend` block), `README.md`
  ("keep `terraform.tfstate` private"), `justfile` `deploy` (reads state
  from `s3://ycgs-use1-terraform/...`).
- **Problem:** following the README creates local state, a second copy
  of the stack, which then collides on the fixed IAM user name. `just
  deploy` runs `eval` on text read from the state object, so anyone who
  can write to that bucket can run commands on the deployer's machine.
- **Fix:** declare the S3 backend (or a partial backend config) and
  document it. Have `deploy` run the two commands itself with values from
  `terraform output`, rather than `eval`.

### 8. Tile textures are not freed when a COG layer is removed {#texture-leak}

**Severity** medium · **Origin** migration

- **Where:** `website/js/cog.js`, `cogLayer()` (`onTileUnload`).
- **Problem:** the band and occupancy textures are destroyed in
  `onTileUnload`. deck.gl calls that when a tile leaves its cache, but not
  when the whole layer goes away. `TileLayer.finalizeState()` calls
  `Tileset2D.finalize()`, which clears the cache without calling it.
  Switching products, clearing a grid slot, or ending a comparison
  therefore leaves float textures for the garbage collector, which frees
  GPU memory late or not at all.
- **Fix:** override `finalizeState` in `FinerCOGLayer` to destroy the
  textures of the tileset's remaining tiles, then call `super`.

### 9. Bad numbers in a render spec hang the tab or break the shader {#spec-edge-cases}

**Severity** medium · **Origin** both

- **Where:** `website/js/mapview.js` `logTicks()` (earlier),
  `website/js/cog.js` `normalizeGlsl()` (migration), `website/js/tiles.js`
  `normalizer()` (earlier).
- **Problem:** nothing validates render specs.
  - **Hang:** a log-scale colormap with `vmin: 0` and a label hangs the
    tab. `logTicks` starts its loop at `log10(0) = -Infinity`, which never
    increments.
  - **Shader fails to compile:** the shader generator writes non-finite
    numbers as `-Infinity` or `NaN`, which is not valid GLSL. This happens
    for a log scale with `vmin <= 0`, for `gamma: 0`, or when the range is
    missing. The layer fails, with only a console message.
  - **ArcGIS tile fails:** with `vmin == vmax`, the CPU colorizer computes
    `0/0` and indexes the color table with `NaN`, which throws for the
    whole tile.
- **Fix:** validate each spec once: finite numbers, `vmax > vmin`,
  `vmin > 0` for log, `gamma > 0`. Reject bad specs in
  `build_catalog.py`, so they never reach the browser.

### 10. One failing product stops all map updates; failures are silent {#errors-stop-rendering}

**Severity** medium · **Origin** both

- **Where:** `website/js/viewer.js` and `grid.js` `render()`;
  `website/js/cog.js` `geotiff()`; `website/js/main.js` `main()`.
- **Problem:**
  - An exception from `compile()` or `productLayers()` escapes `render()`
    inside `requestAnimationFrame`. The next render throws again, so
    titles, layers and the URL stop updating for every product.
  - A COG that fails to open (`geotiff()`) is only logged and never
    retried: the map stays empty with no message.
  - Neither `Deck` sets `onError` or handles `webglcontextlost`.
  - `main()` catches only the catalog load.
- **Fix:** catch errors per product and show them in that map's message
  element. Drop failed COG entries so they are retried. Route deck.gl and
  WebGL errors to `fatal()`.

### 11. The grid's loading counter goes negative {#loading-counter}

**Severity** medium · **Origin** earlier

- **Where:** `website/js/grid.js` `select()` calls
  `LoadingState.reset()` (`mapview.js`).
- **Problem:** `reset()` sets `pending` to 0 while the old product's tile
  requests are still in flight. When they abort, each calls `end()`, so
  `pending` drops below zero. From then on "Loading…" and "N tiles failed"
  appear late or never for that slot.
- **Fix:** do not reset the counter. Or tag requests with a generation
  number and ignore `end()` from older generations.

### 12. URL values are not validated {#url-validation}

**Severity** medium · **Origin** earlier

- **Where:** `website/js/main.js`, the `url-restore` block.
- **Problem:**
  - `#cols=100000000&g=x` makes the grid create 10⁸ slots and freezes the
    tab. Negative or fractional values give a broken layout.
  - `mode=foo` is accepted. The viewer then takes the spy branch without a
    pointer position, so image B is never drawn, and `mode=foo` is written
    back to the URL.
- **Fix:** round and clamp `cols` to the column choices offered (1–6).
  Accept only `swipe`, `opacity` and `spy` for `mode`.

### 13. Hidden layers are dropped and reloaded from scratch {#reloads}

**Severity** medium · **Origin** migration (the cost; the pattern is older)

- **Where:** `website/js/viewer.js` `layers()` (spy mode); `grid.js`
  `render()` (off-screen slots).
- **Problem:** B's layers exist only while the pointer is over the map in
  spy mode, and the grid skips off-screen slots. The old renderer kept
  decoded blocks in its sources, so this cost little. Now each new
  `COGLayer` starts with an empty tile cache, so every time the cursor
  re-enters the map (or a slot scrolls back into view), all tiles are
  fetched and decoded again, and the lens starts out empty.
- **Fix:** keep the layers and pass `visible: false` (or an empty clip)
  instead of dropping them.

### 14. NISAR: rain undercounted early in the search window {#nisar-rain}

**Severity** medium · **Origin** earlier

- **Where:** `scripts/nisar-gcov/select_granule.py`, `candidates()` and
  `precip_before()`.
- **Problem:** hourly precipitation is fetched only from the start of the
  search window. A granule in the first three days of the window gets
  less than 72 hours summed, so it looks drier than it is. Candidates are
  ranked by `precip_72h_mm`, so the ranking can pick it for that reason
  alone. Also, `<=` on both bounds sums 73 hourly values.
- **Fix:** fetch from three days before the window. Use
  `when − 72 h < t <= when`.

### 15. Interrupted runs leave partial files that later runs treat as done {#partial-files}

**Severity** medium · **Origin** earlier

- **Where:**
  - `scripts/common/web.py` `write_cog()` and `write_spec()`;
    `build_catalog.py`.
  - Several `download.py` files that skip existing outputs (ct-impervious,
    ERA5, PRISM, GOES).
  - `icesat2/download.py` `download_atl08()`: it writes
    `atl08_<year>.parquet` before `atl08_20m_<year>.parquet` but checks
    only the first. An interruption between the two leaves a cache that
    never repairs itself, and `create-cog.py` then fails.
- **Problem:** outputs are written straight to their final path. A crash
  leaves a truncated COG or JSON that the next run skips over, or that
  `build_catalog.py` and the deploy pick up.
- **Fix:** add a shared helper that writes to `*.part` and renames into
  place with `os.replace`. Check every output a cached step produces.

### 16. Python dependencies are not pinned {#unpinned-python}

**Severity** medium · **Origin** earlier

- **Where:** the PEP 723 header of every script.
- **Problem:** no versions, no `exclude-newer`, no lock files. A new
  rasterio or GDAL (LERC, COG driver options) or numpy can change outputs
  silently. The npm side, by contrast, is pinned and locked.
- **Fix:** add `[tool.uv] exclude-newer = "<date>"` to each header, or
  commit `uv lock --script` lock files.

### 17. No tests and no CI {#no-tests}

**Severity** medium · **Origin** earlier

- **Problem:** there is no `.github/` and no test suite. The renderer
  was checked against screenshots by hand ([Fixtures and
  benchmark](/build/benchmark)).
- **Fix:** a CI job running:
  - ruff;
  - `node docs/scripts/check-snippets.mjs`;
  - `terraform validate`;
  - small pytest tests of view and grid alignment, hillshade direction
    (which would have caught [2](#hillshade-direction)), and `serve.py`
    range handling.

  Later: a Playwright smoke test that opens each fixture in the viewer
  and the grid, which would have caught [1](#lut-context).

### 18. Performance follow-ups from the migration {#perf-followups}

**Severity** medium · **Origin** migration

These are described in detail in the [migration report](/deck-gl-raster#performance)
and on [Performance](/comparison/performance):

- **Many more requests.** deck.gl-raster makes one range request per COG
  tile. With 40 ms of latency, zooming the 0.5 m COG took 1.76× longer.
  The higher HTTP/2 request limit is not measured on the deployed site.
  deck.gl-raster's unreleased request batching should help; adopt it when
  `COGLayer` uses it.
- **Product switches re-download tiles** shared with the previous product.
  A shared decoded-tile cache keyed by COG URL and tile would avoid it,
  and would also solve [13](#reloads).
- **Frame times are unmeasured on a real GPU.** Under software rendering,
  panning is about 2× slower, and 6× for the `dilate_px` products. Run
  `bench.mjs` on hardware.
- **JPEG COGs are band-interleaved** for geotiff.js, which is no longer
  used. Pixel-interleaved YCbCr would be smaller and need one decode per
  tile instead of three ([Website data](/pipeline/website-data)).
- **Report the three upstream bugs** to deck.gl-raster (multi-band LERC,
  edge clipping, overview choice), so the workarounds in `cog.js` can go
  ([migration report](/deck-gl-raster#upstream-issues-found)).

## Low

### 19. Missing Planet tiles become black pixels {#planet-gaps}

- **Where:** `scripts/planet/create-cog.py`; `scripts/common/web.py`
  `write_cog(kind="jpeg")`.
- **Problem:** `fetch_xyz` returns alpha 0 for missing tiles. The script
  drops alpha and writes a JPEG COG with no mask, so gaps show as black.
  It only prints the fraction.
- **Fix:** fail when the fraction is above zero, or write an internal mask
  and honor it in the renderer.

### 20. Hard-coded dates and versions will go stale {#stale-facts}

- **PRISM:** the "provisional" label and the color range are hard-coded
  (`prism/visualize.py`, `create-cog.py`). The download URL returns
  whatever version PRISM currently serves, which may later be a stable
  release.
- **ICESat-2:** the label "2026 data available through mid-July" is
  repeated in `visualize.py` and `create-cog.py`.
- **CHIRPS:** `find_rainy_days.py` hard-codes `LAST_FINAL` "as of
  2026-10-02".
- **Fix:** derive these from the downloaded data or metadata, and warn
  when values fall outside the color range.

### 21. Duplicated code and constants {#duplication}

- **Pipeline:**
  - The reader scripts copy file names and dates from `download.py`
    (PRISM, VIIRS night lights, VIIRS LST, GOES, ERA5). Changing a date in
    `download.py` silently leaves them on old files. CHIRPS and SMAP
    already import `output_path` from `download`; use that pattern
    everywhere.
  - The NAIP scripts share `acquisition_dates()` and the service
    constants, and NAIP and CT ortho share `fetch_bands`. The ArcGIS
    `website-layers.py` scripts re-declare `SERVICE`, `NATIVE_M` and other
    constants.
  - GOES and VIIRS LST copy the quality-mask overlay code.
  - `render.reproject_to_view` and `web.reproject` differ only in the
    target grid.
  - The Web Mercator world width (`2π × 6378137`) is defined in
    `remote.py` and again inline in `web.py`.
- **Viewer:** hex-color parsing exists three times, `esc` twice, and the
  Web Mercator math in both `tiles.js` and `catalog.js`.
- **Fix:** move the shared pieces into `scripts/common/` and a small
  `website/js/util.js`.

### 22. Dead code and unneeded exports {#dead-code}

- `wms_getmap` and `GIBS_WMS` in `scripts/common/remote.py` have no
  callers ([Remote services](/pipeline/remote)). If kept, palette ("P")
  PNGs need `.convert("RGBA")`.
- The vendored bundle exports `CreateTexture`, which nothing uses
  ([Vendored bundle](/build/vendor)).
- Exported but used only in their own module: `MAX_ZOOM`, `fitZoom`,
  `hexToRgba` (`mapview.js`), `renderArcgisTile` (`tiles.js`), `close`
  (`picker.js`). Unused fields: `Catalog.data`, `Catalog.extentTitle`, and
  the `promise` field of `geotiff()`'s cache entries in `cog.js`.
- `landsat/select_scene.py` imports numpy without using it.
- `icesat2/create-cog.py` `segments()` loads the 20 m data a second time.

### 23. Security hardening {#security-hardening}

These matter only if the catalog or the site were less trusted than they
are, so they are defense in depth:

- **CloudFront** (`terraform/aws/main.tf`): no response-headers policy (no
  HSTS, `X-Content-Type-Options` or CSP) and no access logging.
- **Viewer:**
  - The CPU path compiles catalog expressions with `new Function`
    (`tiles.js`), without the whitelist the GPU path applies.
  - Colors go into `style` attributes unescaped (`mapview.js`).
  - `fatal()` (`main.js`) inserts error messages as HTML. A JSON parse
    error quotes the response, so an HTML error page ends up parsed as
    markup.

### 24. Accessibility gaps {#accessibility}

- The tabs lack `aria-controls` and arrow-key navigation.
- The compare-mode buttons form a `radiogroup` but use `aria-pressed`
  rather than `role=radio`/`aria-checked`.
- The swipe slider has no `aria-valuenow`.
- The picker button has no `aria-expanded`.
- `.map-message` is not a live region.
- Icon-only buttons (◀ ▶ + − ⤢ ×) rely on `title` and need `aria-label`.
- Rearranging the grid works only with mouse drag and drop. Add move
  buttons or keyboard shortcuts (medium for keyboard users).
- There is no `hashchange` listener, so editing the URL of an open tab does
  nothing.

### 25. Smaller bugs {#small-bugs}

- **Identity render with fewer than 3 bands:** an 8-bit 1-band COG throws
  on every tile, and a 1-band float COG renders red only (`cog.js`
  `compile`, `loadTile`).
- **ArcGIS reads:**
  - The decoded `ImageBitmap` is never closed.
  - `read()` retries permanent errors (HTTP 4xx, JSON error bodies) as
    well as transient ones (`tiles.js`).
- **Basemap tiles** report no loading or failure state (`tiles.js`
  `xyzLayers`).
- **Benchmark** (`bench.mjs`):
  - `before=URL` arguments are cut at a second `=`.
  - Runs that time out are dropped from the medians without notice,
    which biases them toward fast runs.
  - The default Chromium path is specific to one machine.
- **`fixtures.py` `export()`:** with `format=jpgpng`, a mix of JPEG
  (3-band) and PNG (4-band) chunks fails with a shape error, and an ArcGIS
  JSON error sent with HTTP 200 surfaces as an unclear rasterio error.
  `remote.arcgis_export_image` already handles both; reuse it.
- **`render.percentiles`** raises `IndexError` on all-NaN data, and
  `stretch` divides by zero when `vmin == vmax`.
- **Retries are inconsistent:** some scripts use plain `requests.get` with
  no retries (GOES download, NISAR selection, landmark geocoding), while
  `common.remote.session()` has them.
- **No just recipe makes the figures:** the README describes the figures
  workflow, but `just build` runs only the website scripts. Add
  `just figures`.
- **SMAP `download.py`** has no skip-if-exists, unlike its siblings, so
  every `just download` transfers the global field again.
- **ICESat-2 `download.py`:** the docstring says the sample lines are
  2025–2026 passes, but `select_lines` takes them from all seasons.
