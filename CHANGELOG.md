# Changelog

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
