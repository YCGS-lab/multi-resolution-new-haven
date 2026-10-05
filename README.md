# Satellite data for New Haven, CT

Showing what New Haven, CT looks like at different spatial resolutions.

## Layout

- `scripts/<dataset>/` — PEP 723 scripts, run with `uv run scripts/<dataset>/<script>.py`
  - `download.py` → `data/<dataset>/`, then `visualize.py` → `figures/<dataset>/`
  - `visualize-remote.py` for datasets read straight from a tile / image service (no download step)
  - `create-cog.py` → `website/image-data/<dataset>.tif` + `.json`, or `website-layers.py` → `website/image-data/<dataset>.json`, for the website
- `scripts/common/` — shared view definitions, resampling, figure output, tile/ImageServer/WMS clients, and website data (`web.py`)
- `scripts/website/` — `build_catalog.py` → `website/catalog.json` (the website's image menu), `serve.py` (local server)
- `data/landmarks.json` — landmark coordinates (from `scripts/landmarks/geocode.py`); other data, figures and website image data are not tracked

## Views

Every map is rendered on one of two fixed Web Mercator grids (3840×2160, 16:9), so
figures of the same view are pixel-aligned across datasets:

| View | Center | Extent (ground) | Output pixel |
|---|---|---|---|
| `greater` — Greater New Haven | 41.3039, −72.9193 | 21.5 × 12.1 km | 5.6 m |
| `central` — Central New Haven and Yale | 41.3136, −72.9238 | 3.8 × 2.16 km | 1.0 m |

Data are subset to (at least) the view and resampled onto the grid with nearest
neighbour when coarser than the output pixels, so native pixels show as blocks and
partial pixels are cropped at the image edges. Each product is written twice:
`<view>_<product>.png` (data only) and `<view>_<product>_labeled.png`.

## Datasets

| Dataset | Native resolution | Date / period | Source | Products |
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

## Website

`website/` is an interactive map viewer built on [deck.gl](https://deck.gl) (from unpkg) and
[geotiff.js](https://geotiffjs.github.io/) (from jsDelivr). It does not use the figures: it draws
each image itself, tile by tile, over the Greater New Haven extent, from

- **local Cloud-Optimized GeoTIFFs** of the real values (temperature, reflectance, elevation,
  backscatter, ...), written by each dataset's `create-cog.py` to `website/image-data/`, or
- **image services read directly** (no local copy), declared by `website-layers.py`: the CT ECO
  ImageServers (orthoimagery and NAIP as the server's 8-bit band values, shown as is; lidar DEM / DSM
  as float elevations), the USGS 3DEP ImageServer (float elevations), and XYZ map tiles (the
  ICESat-2 basemap, and the street maps).

Each dataset's `.json` gives its sources and, per product, the *render spec* that turns values
into colors: band combinations and stretches (e.g. Landsat composites, NISAR HH / HV / HH−HV in
dB), colormaps with their value ranges (also drawn as the colorbar), hillshading (computed in
the browser for the lidar and 3DEP DEMs), and categorical colors (with a legend).
`build_catalog.py` gathers them into `website/catalog.json`.

```sh
uv run scripts/<dataset>/create-cog.py        # or website-layers.py; see below
uv run scripts/website/build_catalog.py       # website/image-data/*.json -> website/catalog.json
uv run scripts/website/serve.py               # from anywhere; serves the repository root
# open http://localhost:8000/website/
```

`serve.py` is needed instead of `python -m http.server` because the COGs are read with HTTP
range requests.

| Script | Datasets |
|---|---|
| `create-cog.py` | landsat, viirs-lst, goes-lst, viirs-nightlights, smap, chirps, era5-land, prism, icesat2, nisar-gcov, planet, aster-dem, ct-impervious-2023 |
| `website-layers.py` | ct-ortho-2023, naip, ct-lidar-2023, 3dep, streetmap |

`streetmap` adds reference maps that need no credentials: OpenStreetMap Standard, Esri World
Street Map, and the USGS National Map topographic base map (public domain). Map tiles are
drawn at the zoom level that keeps their labels at about their design size, and scaled
smoothly. (CARTO basemaps now need an API key; Google Maps tiles need a key and may only be
used through Google's own map APIs.)

COGs are on Web Mercator grids over the extent at the native resolution, or, for data coarser
than 30 m, on a ~30 m grid (nearest neighbor) so each native pixel keeps its footprint.
Compression: LERC (lossy, with a per-dataset maximum error) for real values, JPEG for the
Planet basemap (stored locally so the API key stays out of the browser), lossless DEFLATE for
the rasterized impervious-surface classes (0.5 m). NISAR is stored locally because
titiler-cmr is too slow for interactive tiles.

- **Viewer**: pick an image from a grouped, searchable menu (`[` / `]` step through an image's
  group, e.g. the ERA5 timesteps). Pan and zoom are limited to the Greater New Haven extent;
  native pixels stay sharp blocks when zoomed in. **Compare** adds image B over A, revealed by
  a swipe divider, by fading (opacity), or inside a lens that follows the cursor (spy).
- **Grid**: any number of images with synchronized pan and zoom (one WebGL canvas, one
  deck.gl view per slot). Empty slots say "Add image"; **Add row** adds slots; **Rearrange**
  lets you drag images onto other slots to swap them.
- Titles, axes, colorbars and legends are HTML; landmarks and the scale bar can be toggled
  with **Labels** (or `L`). The current images, comparison and grid are kept in the URL.

The menu's groups and labels are set in `TREE` in `build_catalog.py`; products not listed
there appear under "Other".

## Credentials

- NASA Earthdata: `~/.netrc` (used by `earthaccess`)
- Planet, Copernicus CDS, AWS (Landsat L1 requester-pays): `_credentials.toml` (not tracked),
  with keys `planet_api_key`, `cds_api_key`, `aws_access_key_id`, `aws_secret_access_key`
