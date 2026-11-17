# Bowerbird: New Haven, CT at many resolutions

Showing what New Haven, CT (and, on the website, the rest of the contiguous US) looks like
in satellite, aerial and model data at different spatial resolutions:

- **Figures**: pixel-aligned maps of Greater New Haven and central New Haven, one per dataset
  and product, made by Python scripts.
- **Bowerbird**, an interactive map viewer (`website/`): every dataset drawn tile by tile in
  the browser, for any timestep, with comparison, a synchronized grid and animation.
- **A tiler** (`tiler/`, titiler on AWS Lambda) for the datasets browsers cannot read
  directly (NASA HDF5 and NetCDF in S3, COGs without CORS).

**Developer documentation:** <https://ycgs-lab.github.io/multi-resolution-new-haven/>
(source in `docs/`; `just docs` serves it locally). Changes by version: [CHANGELOG.md](CHANGELOG.md)
(current: 0.8.2).

## Layout

| Path | What |
|---|---|
| `scripts/<dataset>/` | PEP 723 scripts, run with `uv run scripts/<dataset>/<script>.py` (see below) |
| `scripts/common/` | Shared view definitions, resampling, figure output, tile / ImageServer / WMS clients, website data (`web.py`) |
| `scripts/website/` | `build_catalog.py` (the website's image menu), `Caddyfile` (local server), `vendor/` (deck.gl bundle), `benchmark/` |
| `scripts/aws-tests/` | End-to-end tests of the AWS deployments (deploy, check, destroy) |
| `website/` | Bowerbird, the map viewer: static HTML, CSS and ES modules, no build step |
| `tiler/` | The tiler: titiler with dataset presets and titiler-cmr, its Lambda handler and tests |
| `terraform/aws/` | Hosting for `website/`: private S3 bucket, CloudFront, a deploy-only identity |
| `terraform/tiler/` | The tiler in three AWS regions behind one CloudFront distribution, with a lookup cache and a cost guard |
| `terraform/places/` | Place search API (Amazon Location Places behind a Lambda) |
| `terraform/complete/` | Website, tiler and place search deployed together, wired to each other |
| `docs/` | Developer documentation (VitePress), published to GitHub Pages by `.github/workflows/docs.yml` |
| `data/landmarks.json` | Landmark coordinates (from `scripts/landmarks/geocode.py`) |

Other data (`data/`), figures (`figures/`) and website image data (`website/image-data/`,
`website/catalog.json`) are not tracked.

Each dataset's scripts:

- `download.py` → `data/<dataset>/`, then `visualize.py` → `figures/<dataset>/`;
  `visualize-remote.py` for datasets read straight from a tile / image service (no download step)
- `website-layers.py` → `website/image-data/<dataset>.json`: data the website reads live, for any timestep
- `create-cog.py` → `website/image-data/<dataset>.tif` and its `.json`: data pre-built for one
  timestep (`<dataset>-prebuilt.json` where the dataset is also live, `landsat-pan` for the Landsat
  panchromatic band)

## Figures

Every figure is rendered on one of two fixed Web Mercator grids (3840×2160, 16:9), so
figures of the same view are pixel-aligned across datasets:

| View | Center | Extent (ground) | Output pixel |
|---|---|---|---|
| `greater` — Greater New Haven | 41.3039, −72.9193 | 21.5 × 12.1 km | 5.6 m |
| `central` — Central New Haven and Yale | 41.3136, −72.9238 | 3.8 × 2.16 km | 1.0 m |

Data are subset to (at least) the view and resampled onto the grid with nearest
neighbour when coarser than the output pixels, so native pixels show as blocks and
partial pixels are cropped at the image edges. Each product is written twice:
`<view>_<product>.png` (data only) and `<view>_<product>_labeled.png`.

| Dataset | Native resolution | Date / period (figures) | Source | Products |
|---|---|---|---|---|
| `landsat` | 30 m (pan 15 m, thermal 100 m) | 2024-08-27 | Planetary Computer (L2), AWS requester-pays (L1 pan) | truecolor, cir, veg, urban, lst, pan |
| `viirs-lst` | 750 m swath | 2026-06-03 17:52 UTC | VNP21 v002 (Suomi NPP) | lst |
| `goes-lst` | 2 km at nadir (~2.1×3.1 km here) | 2026-06-03 18:01 UTC | GOES-19 ABI-L2-LSTC (NOAA AWS) | lst |
| `viirs-nightlights` | 15″ (~350×460 m) | 2025 annual | Black Marble VNP46A4 | radiance |
| `smap` | 9 km | 2026-07-30 | SPL4SMGP v008 | sm_rootzone |
| `chirps` | 0.05° | 2026-07-29 | CHIRPS v3 daily | precip |
| `era5-land` | 0.1° | 2026-07-20 (4 times) | Copernicus CDS | t2m_sunrise, t2m_midday, t2m_sunset, t2m_night |
| `prism` | 30″ (~800 m) | July 2026 | PRISM | tmean |
| `icesat2` | 20 m segments / photons | May–Sep 2025–2026 (+ all years) | SlideRule Earth | canopy_height, canopy_height_allyears, tracks, profile_N |
| `nisar-gcov` | 10 m (frequency A) | 2026-07-17 09:59 UTC | NISAR L2 GCOV (ASF) via titiler-cmr (openveda.cloud) | balanced, vegetation, urban, water, hh, hv |
| `planet` | 4.8 m | July 2026 | Planet monthly basemap | truecolor |
| `naip` | 0.3 m | July 2023 | CT ECO NAIP_2023 ImageServer | truecolor, cir |
| `ct-ortho-2023` | 0.076 m (3 in) | spring 2023 (leaf-off) | CT ECO Ortho_2023 ImageServer | truecolor, cir |
| `ct-lidar-2023` | 2 ft (0.6 m) | spring 2023 | CT ECO Statewide2023 / MaxSurfaceHeight_2023 | elevation, hillshade, surface |
| `3dep` | ~1 m | best available | USGS 3DEP ImageServer | elevation, hillshade |
| `aster-dem` | 1″ (~30 m) | 2000–2013 | ASTGTM v003 | elevation, hillshade |
| `ct-impervious-2023` | vector polygons | 2023 | CT GIS Office FeatureServer | classes, impervious |

Some scripts have extra steps: `landsat/select_scene.py`, `nisar-gcov/select_granule.py`, `era5-land/select_day.py`,
`chirps/find_rainy_days.py` pick the scene/date; the rest read their choice from code or
`data/`.

## Website (Bowerbird)

`website/` is an interactive map viewer built on [deck.gl](https://deck.gl) and
[deck.gl-raster](https://github.com/developmentseed/deck.gl-raster) (bundled in `website/vendor/`
by `scripts/website/vendor/`), styled after [geospatial.yale.edu](https://geospatial.yale.edu/)
(Yale blue header with the YCGS wordmark, Yale typefaces). It does not use the figures: it
draws each image itself, tile by tile, anywhere in the contiguous US (and beyond, where the
data exist), from

- **data read live** for the timestep the user picks (no local copy), declared by
  `website-layers.py`:
  - the Microsoft Planetary Computer: Landsat 8-9 Level-2 and NAIP (every year flown, CONUS);
  - the CT ECO ImageServers (orthoimagery 1934–2023, lidar 2016 / 2023) and USGS 3DEP;
  - NISAR through the public titiler-cmr (slow: 5–10 s per tile);
  - Planet monthly basemaps and ERA5-Land (ECMWF's ARCO Zarr store, any hour since 1950),
    with the user's own API keys;
  - this repository's tiler: SMAP, Black Marble night lights, GOES and VIIRS daily LST, CHIRPS
    (*cloud-only*, see below);
  - XYZ street maps (OpenStreetMap, Esri World Street Map, USGS topo); or
- **local Cloud-Optimized GeoTIFFs** of the real values for one timestep, over Greater New Haven
  (VIIRS and GOES LST, PRISM, CHIRPS, SMAP and Black Marble snapshots, Landsat pan, ASTER,
  ICESat-2, CT impervious), written by each dataset's `create-cog.py`.

COGs are read and drawn by deck.gl-raster and colored on the GPU; live tiles are colored in
the browser. Each dataset's `.json` gives its sources and, per product, the *render spec*
that turns values into colors (band combinations and stretches, colormaps and colorbars,
hillshading, categorical legends). `build_catalog.py` gathers them into `website/catalog.json`;
the menu's groups and labels are set in its `TREE`.

| Script | Datasets |
|---|---|
| `website-layers.py` | 3dep, chirps, ct-lidar, ct-ortho, era5-land, goes-lst, landsat, naip, nisar-gcov, planet, smap, streetmap, viirs-lst, viirs-nightlights |
| `create-cog.py` | landsat (pan only), viirs-lst, goes-lst, viirs-nightlights, smap, chirps, prism, icesat2, aster-dem, ct-impervious-2023 |

Features:

- **Viewer**: pick an image from a grouped, searchable menu; **Compare** adds image B over A
  (swipe, opacity or a spy lens; B starts one timestep earlier; ⇆ swaps them).
- **Grid**: any number of images with synchronized pan and zoom, each with its own time.
- **Animation**: loads every frame of a date range for the area in view, then plays it.
- **Time**: drop-downs, calendars (dates without data in view grayed out), previous / next,
  filters such as max cloud cover (default 20%), and for Landsat and NISAR a mosaic of a date
  window. NAIP's title shows when and where the imagery in view was flown.
- **Place search** in the header, with starred places; **Location tools** for the selected
  place (ICESat-2 photon profiles of Greater New Haven).
- **Empty areas** are told apart, with a key under each map: no scene, no data in a scene
  (clouds, water, fill), and failed tiles (hatched red, "Click to retry").
- **Credentials** (🔑): Planet and Copernicus CDS API keys, kept in the browser and sent only
  to the provider.
- Keyboard shortcuts, screen-reader labels and reflow at 320 px (WCAG 2.1 AA audit in the docs).
  The current images, comparison, grid and place are kept in the URL.

Details: [Map viewer](https://ycgs-lab.github.io/multi-resolution-new-haven/website/) in the docs.

### Run it locally

```sh
uv run scripts/<dataset>/website-layers.py    # or create-cog.py
uv run scripts/website/build_catalog.py       # website/image-data/*.json -> website/catalog.json
just serve                                    # http://localhost:8000/
```

`website-layers.py` scripts need no downloads or credentials, so a local test needs only
those and `build_catalog.py`; the `create-cog.py` datasets appear once built (`just download`
and `just build` do everything). The local server is [Caddy](https://caddyserver.com/)
(`scripts/website/Caddyfile`) because COGs are read with HTTP range requests, which
`python -m http.server` does not support.

**Cloud-only datasets** (SMAP, Black Marble, GOES LST, VIIRS daily LST, CHIRPS live) are read by
the tiler (`services.tiler` in `website/env.json`). The website decides at runtime whether it
runs "in the cloud" (`"cloud": "auto"`: any host but localhost); locally these datasets are
grayed out with a cloud icon. To test them locally, run the tiler (`tiler/serve-local.sh`, port
8100) and open `http://localhost:8000/?cloud=1&service.tiler=http://localhost:8100`.

## Deploying

- **Everything** (website, tiler, place search): `terraform/complete`, which writes the
  deployed `env.json` with the tiler's and place search's URLs. Works with OpenTofu or Terraform.
- **The website alone**: `terraform/aws` (private S3 bucket behind CloudFront, plus an IAM user
  whose key can only assume a deploy role that syncs the bucket and invalidates the cache).
- **Updating the website**: `just deploy` runs the stack's `deploy_commands` (sync `website/`,
  leaving the managed `env.json` alone, and invalidate CloudFront).
- **The docs** are built and published to GitHub Pages by `.github/workflows/docs.yml` on every
  push to `main` that touches them or the code they show.

Step by step, including custom domains and the AWS end-to-end tests:
[Build, deploy, test](https://ycgs-lab.github.io/multi-resolution-new-haven/build/).

## `just` recipes

| Recipe | What |
|---|---|
| `just download` | Download `data/` for every dataset (picks the Landsat scene and NISAR granule first) |
| `just build` | Write `website/image-data/` (all `create-cog.py`, `website-layers.py`) and `website/catalog.json` |
| `just serve` | Serve `website/` at http://localhost:8000/ |
| `just vendor` | Rebuild `website/vendor/` (deck.gl, deck.gl-raster, zarrita) |
| `just docs` | Developer documentation at http://localhost:5173/ |
| `just deploy` | Sync `website/` to the deployed bucket and invalidate CloudFront |
| `just prefill-lookups` | Pre-fill the tiler's lookup cache with New Haven's CMR searches |
| `just is2` | Rebuild the ICESat-2 data for the website |

## Credentials

For the scripts (the website's keys are entered in the browser, see above):

- NASA Earthdata: `~/.netrc` (used by `earthaccess`)
- Planet, Copernicus CDS, AWS (Landsat L1 requester-pays): `_credentials.toml` (not tracked),
  with keys `planet_api_key`, `cds_api_key`, `aws_access_key_id`, `aws_secret_access_key`
