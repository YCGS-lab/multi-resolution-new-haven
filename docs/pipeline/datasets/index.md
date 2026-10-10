# Datasets

Each dataset has a folder under `scripts/` with the scripts described in the
[pipeline overview](../). The scripts follow the shared pattern closely, so
these pages skip what is routine and focus on each dataset's own choices:
which product and date, how it is read, and what had to be worked around.

## All datasets

| Dataset | Native resolution | Date | Source | Website reads | Credentials | Page |
|---|---|---|---|---|---|---|
| `ct-ortho-2023` | 7.6 cm | spring 2023 | CT ECO Ortho_2023 ImageServer | live service | none | [Optical](./optical#ct-orthoimagery-2023) |
| `naip` | 0.3 m | July 2023 | CT ECO NAIP_2023 ImageServer | live service | none | [Optical](./optical#naip) |
| `planet` | 4.8 m | July 2026 | Planet monthly basemap tiles | local JPEG COG | Planet key | [Optical](./optical#planet) |
| `landsat` | 30 m (pan 15 m, thermal 100 m) | 2024-08-27 | Planetary Computer (L2), AWS (L1 pan) | local COGs | AWS key (pan) | [Optical](./optical#landsat-8) |
| `viirs-lst` | 750 m swath | 2026-06-03 | NASA VNP21 | local COG | Earthdata | [Temperature](./temperature#viirs-lst) |
| `goes-lst` | 2 km (2.1 × 3.1 km here) | 2026-06-03 | NOAA GOES-19 on AWS | local COG | none | [Temperature](./temperature#goes-lst) |
| `era5-land` | 0.1° | 2026-07-20, 4 times | Copernicus CDS | local COG | CDS key | [Temperature](./temperature#era5-land) |
| `prism` | 800 m | July 2026 | PRISM web service | local COG | none | [Temperature](./temperature#prism) |
| `smap` | 9 km | 2026-07-30 | NASA SPL4SMGP | local COG | Earthdata | [Water and lights](./water-and-lights#smap) |
| `chirps` | 0.05° | 2026-07-29 | CHIRPS v3 (UCSB) | local COG | none | [Water and lights](./water-and-lights#chirps) |
| `viirs-nightlights` | 15″ (~350 × 460 m) | 2025 | NASA Black Marble VNP46A4 | local COG | Earthdata | [Water and lights](./water-and-lights#viirs-black-marble) |
| `ct-lidar-2023` | 0.6 m (DSM 0.9 m) | spring 2023 | CT ECO elevation ImageServers | live service | none | [Elevation](./elevation#ct-lidar-2023) |
| `3dep` | ~1 m | best available | USGS 3DEP ImageServer | live service | none | [Elevation](./elevation#usgs-3dep) |
| `aster-dem` | 1″ (~30 m) | 2000–2013 | NASA ASTGTM v003 | local COG | Earthdata | [Elevation](./elevation#aster-gdem) |
| `icesat2` | 20 m segments, photons | 2019–2026 | SlideRule Earth | local COG + OSM | none | [Vegetation](./vegetation-and-land-cover#icesat-2) |
| `ct-impervious-2023` | vector polygons (0.5 m raster) | 2023 | CT GIS Office FeatureServer | local COG | none | [Vegetation](./vegetation-and-land-cover#ct-impervious-surface-2023) |
| `nisar-gcov` | 10 m | 2026-07-17 | NISAR L2 GCOV via titiler-cmr | local COG | Earthdata | [Radar](./radar) |
| `streetmap` | map tiles | current | OSM, Esri, USGS topo | live tiles | none | [Maps and landmarks](./maps-and-landmarks#street-maps) |
| `landmarks` | 4 points | | OSM Nominatim | in `catalog.json` | none | [Maps and landmarks](./maps-and-landmarks#landmarks) |

## Patterns across datasets

::: warning Design decision: chosen dates, not latest data
Each dataset shows one carefully chosen scene or day. The choice is
documented in the code (docstring or constants) and sometimes made by a
script:
- Landsat: newest clear summer scene.
- NISAR: driest ascending pass.
- ERA5-Land: the clearest day of summer.
- CHIRPS: a wet day with a clear gradient across the area.
- SMAP: the day after the CHIRPS storm.
- GOES: the hourly scan closest in time to the VIIRS overpass, so the two
  can be compared.

Re-running a download gives the same data, so figures are reproducible.
:::

::: tip Standard practice: subset early, cache downloads
Downloads read only the area of the views plus a pad (one or more native
pixels) where the service allows it: windowed COG reads, HDF5 ranged reads,
bounding-box queries. They skip files that already exist. A few services
make that impossible: VIIRS swath files and the PRISM zip are downloaded
whole and cut down locally.
:::

::: warning Design decision: website stretches can differ from the figures
The figures stretch imagery (NAIP, CT ortho) with percentiles and a gamma
correction. The website shows the services' own 8-bit values unstretched
(`identity`), because it reads them live. Elevation figures use a per-view
range; the website uses the Greater New Haven range at every zoom.
:::

The dataset pages show only the notable blocks of each script. Every block
shown is a region in the source file, so search the file for `region <name>`
to see it in context.
