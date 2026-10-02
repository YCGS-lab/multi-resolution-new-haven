# Satellite data for New Haven, CT

Showing what New Haven, CT looks like at different spatial resolutions.

## Layout

- `scripts/<dataset>/` — PEP 723 scripts, run with `uv run scripts/<dataset>/<script>.py`
  - `download.py` → `data/<dataset>/`, then `visualize.py` → `figures/<dataset>/`
  - `visualize-remote.py` for datasets read straight from a tile / image service (no download step)
- `scripts/common/` — shared view definitions, resampling, figure output, and tile/ImageServer/WMS clients
- `data/landmarks.json` — landmark coordinates (from `scripts/landmarks/geocode.py`); other data and all figures are not tracked

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
| `viirs-lst` | 375 m swath | 2026-10-02 (NRT only) | LANCE VJ221IMG_NRT | lst |
| `viirs-nightlights` | 15″ (~350×460 m) | 2025 annual | Black Marble VNP46A4 | radiance |
| `smap` | 9 km | 2026-07-30 | SPL4SMGP v008 | sm_rootzone |
| `chirps` | 0.05° | 2026-07-29 | CHIRPS v3 daily | precip |
| `era5-land` | 0.1° | 2026-07-20 (4 times) | Copernicus CDS | t2m_sunrise, t2m_midday, t2m_sunset, t2m_night |
| `prism` | 30″ (~800 m) | July 2026 | PRISM | tmean |
| `icesat2` | 20 m segments / photons | May–Sep 2025–2026 (+ all years) | SlideRule Earth | canopy_height, canopy_height_allyears, tracks, profile_N |
| `planet` | 4.8 m | July 2026 | Planet monthly basemap | truecolor |
| `naip` | 0.3 m | July 2023 | CT ECO NAIP_2023 ImageServer | truecolor, cir |
| `ct-ortho-2023` | 0.076 m (3 in) | spring 2023 (leaf-off) | CT ECO Ortho_2023 ImageServer | truecolor, cir |
| `ct-lidar-2023` | 2 ft (0.6 m) | spring 2023 | CT ECO Statewide2023 / MaxSurfaceHeight_2023 | elevation, hillshade, surface |
| `3dep` | ~1 m | best available | USGS 3DEP ImageServer | elevation, hillshade |
| `aster-dem` | 1″ (~30 m) | 2000–2013 | ASTGTM v003 | elevation, hillshade |
| `ct-impervious-2023` | vector polygons | 2023 | CT GIS Office FeatureServer | classes, impervious |

Some scripts have extra steps: `landsat/select_scene.py`, `era5-land/select_day.py`,
`chirps/find_rainy_days.py` pick the scene/date; the rest read their choice from code or
`data/`.

## Credentials

- NASA Earthdata: `~/.netrc` (used by `earthaccess`)
- Planet, Copernicus CDS, AWS (Landsat L1 requester-pays): `_credentials.toml` (not tracked),
  with keys `planet_api_key`, `cds_api_key`, `aws_access_key_id`, `aws_secret_access_key`
