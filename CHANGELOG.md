# Changelog

## 0.8.2 (2026-11-04)

- `tiler_snap_start = false` no longer shows a change (and publishes a new Lambda version)
  on every plan: SnapStart off is again no `snap_start` block, which the AWS provider
  sends as `ApplyOn None` and reads back as no block. 0.8.1's explicit `None` block was
  unnecessary, and its `snap_start` output failed once SnapStart was off.

## 0.8.1 (2026-11-04)

- Tiler Lambda versions: only the live one is kept (`tiler_keep_versions`, default 1;
  was 3). Each SnapStart version's cached snapshot is billed around the clock whether or
  not it is invoked, so an old version cost as much as the live one. Changing the setting
  prunes right away; rolling back now means redeploying an earlier ref.
- SnapStart can be turned off per deployment (`tiler_snap_start`, default on everywhere),
  for a deployment that is rarely used: its first request after a pause then pays a full
  cold start instead of ~$8/month per 2 GB of cache.

## 0.8 (2026-11-04)

- NAIP:
  - the title shows when and where the imagery in view was flown, e.g. "2023, flown
    5 Jul – 11 Jul 2023 (CT)", with one range per state across a state line;
  - "Native resolution" gives its resolution (0.3 m, 0.6 m, 1 m; per state where they
    differ), in the viewer, grid and animation;
  - the Connecticut-only note is gone. The years offered follow the area in view, as
    before: each state is flown on its own cycle.
- Failed tiles:
  - "N tiles failed to load. Click to retry" requests only the failed tiles again, for
    image-service and local COG tiles alike;
  - failed tiles are hatched in red;
  - a failed ERA5 (Zarr) read no longer re-requests itself endlessly.
- Empty areas told apart: inside a scene but no data (clouds, water, fill) shows gray dots
  on white, for products whose date search gives scene footprints (Planetary Computer
  STAC, NASA CMR); "no scene" stays plain gray; failed tiles are hatched. A key under each
  map explains them.
- Animation:
  - no blink between frames: the frame on screen stays underneath until the next has
    loaded;
  - step buttons |◀ ▶|.
- Live tiles are never requested below a product's minimum zoom (NAIP in a 2-column grid
  got HTTP 400).
- Benchmarks of v0.7 against v0.8 live: `docs/benchmarks/2026-11-04.md`.

## 0.7 (2026-11-04)

- Footer with Yale's required links, as on geospatial.yale.edu: Accessibility at Yale (Yale
  Policy 1605), Privacy Policy and the copyright notice. A Keyboard shortcuts dialog opens
  from the footer too.
- Accessibility (WCAG 2.1 AA; audit and fixes in `docs/website/accessibility.md`):
  - **Keyboard:**
    - the maps have a visible focus ring;
    - Space and the arrow keys no longer hijack buttons;
    - the grid can be rearranged with Earlier / Later buttons;
    - the tabs and compare mode follow the ARIA keyboard patterns;
    - popups close when focus leaves them, and focus never drops to the page;
    - there is a skip link;
    - the single-key shortcuts act only on the map or panel.
  - **Screen readers:**
    - every icon button, map, slider, picker and grid slot has a name;
    - place search is an announced combobox;
    - map notices, tile failures and animation loading are announced.
  - **Small screens and zoom:** the header and the controls reflow at 320 px wide (or
    400% zoom); font sizes follow the browser's text size.
  - **Visual:**
    - muted text and control borders meet contrast (4.5:1 and 3:1);
    - no text is below 12 px, and icon buttons are at least 24 px;
    - ICESat-2 photon classes can be shown one by one.
  - **Motion:** the animation runs at up to 3 frames/s, and `prefers-reduced-motion` turns
    off map inertia and smooth scrolling.

## 0.6 (2026-10-30)

- Website renamed **Bowerbird**, with a bowerbird-and-bower icon in the header and as the
  favicon.
- Place search in the header: debounced autocomplete through a new place search API
  (`terraform/places`: Amazon Location Places v2 behind a Lambda and a throttled HTTP API,
  wired into `terraform/complete` and covered by the cost guard), plus starred places
  (Greater New Haven, Donnelly, Idaho). The selected place is kept in the URL, marked on
  the maps, and the reset buttons return to it.
- Location-specific tools menu, keyed to the selected place; ICESat-2 photon profiles moved
  there from its tab.
- Dataset picker: Street maps first; the Connecticut datasets and the pre-built Greater New
  Haven layers (labeled as such) under Location-specific at the bottom; datasets with no
  data in view are dimmed but selectable.
- Compare: swap A and B. Landmark labels and the Labels toggle removed; the scale bar is
  always shown.
- Viewer and Animation carry the dataset, date and view (center and zoom) across when
  switching tabs.
- Fixes: Planetary Computer mosaics (Landsat, NAIP) after its register response changed;
  colorbar outline around the extension arrows; latitude axis sized to fit its longest
  label. Example dates removed; Landsat max cloud cover defaults to 20%.

## 0.5.1 (2026-10-21)

- Tiler module: the prune scheduler's IAM role name fits AWS's 64-character limit for
  longer deployment names (`<name>-sched-<region>`; it failed for
  `multi-resolution-new-haven-prod`).
- `just deploy` reads the current Prod state (`ycgs/newhaven-satellite-viewer`), whose
  deploy commands leave the OpenTofu-managed `env.json` alone.

## 0.5 (2026-10-19)

- Tiler lookup cache (DynamoDB, per region): CMR granule searches once per zoom-8 parent
  tile, GOES hour listings and settled `/times` windows are stored and shared across
  execution environments; a weekly prune job revalidates them. `just prefill-lookups`
  fills it with New Haven's CMR searches ahead of time.
- Tiler caching and cost: settled fixed-time tiles kept a year in CloudFront, Origin Shield
  in front of each regional tiler, reserved concurrency by default, and a cost guard
  (CloudFront alarms, kill switch, budget backstop).
- Tiler: CORS headers on preset error responses.
- Website and catalog: "More info" and "Data access" links for every dataset, next to the
  time under the title.
- Docs: lookup cache page (measured CMR latency, benefit, cost, storage options) and
  evaluations of a rendered-tile cache and a hybrid Icechunk store; `.node-version` and a
  docs rendering fix.

## 0.4 (2026-10-16)

- `terraform/complete`: the website and the tiler deployed together, wired to each other.
- Website: an example timestep per dataset (Example button); animation loads can be
  cancelled, with an estimate of the frame cache needed; ICESat-2 map basemap drop-down.
- VIIRS daily 1 km LST (VNP21A1D v002): tiler preset `viirs-lst-daily` and a live layer on
  the website (the 750 m swath stays pre-built).
- `just is2` rebuilds the ICESat-2 data.

## 0.3 (2026-10-16)

- Tiler module (`terraform/tiler`) deployed and tested end to end in AWS (36/36 smoke
  checks): waits for active Lambda versions; S3 credentials endpoint.

## 0.2 (2026-10-16)

- Website: COGs read and drawn with deck.gl-raster, overviews picked to the screen's
  resolution; benchmark and performance write-up.
- Website: time selection, live data sources, credentials, cloud-only datasets,
  comparison through time, animation and ICESat-2 tabs; coverage across the contiguous US.
- ERA5-Land read from ECMWF's ARCO Zarr store instead of CDS jobs and GRIB.
- Tiler app (titiler with dataset presets, titiler-cmr) and its OpenTofu module, with docs.
- VitePress documentation site for the whole codebase.
- AWS test scripts (website module, requester-pays Landsat, tiler); local serving with Caddy.
- Fixes: colormap COG layers drawn black, hillshades lit from the southeast.

## 0.1 (2026-10-06)

- Figure pipeline for Greater New Haven: shared view grids and rendering, landmarks, and
  datasets from 3DEP, Landsat 8, ERA5-Land, PRISM, SMAP L4, CHIRPS, Planet, NAIP, CT ECO
  orthoimagery, lidar and impervious surface, ASTER GDEM, ICESat-2, VIIRS LST and Black
  Marble, GOES-19 LST and NISAR GCOV.
- deck.gl web viewer rendered from COGs and image services, with street maps, styled after
  geospatial.yale.edu.
- Terraform for the AWS website infrastructure; `just download`, `build` and `deploy`.
