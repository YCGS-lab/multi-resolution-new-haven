# Water and night lights

Three coarse datasets: SMAP soil moisture (9 km), CHIRPS precipitation
(0.05°, ~5 km) and VIIRS Black Marble night lights (~400 m). Their scripts
are short and mostly follow the shared pattern. The interesting parts are
in how each download reads only what it needs.

## SMAP

**SPL4SMGP v008 root-zone soil moisture, 9 km EASE-Grid 2.0, 2026-07-30
15:00–18:00 UTC.** Scripts: `download.py`, `visualize.py`, `create-cog.py`
(the pre-built snapshot, dataset `smap-prebuilt`), `website-layers.py` (the
live, cloud-only dataset).

::: warning Design decision: cloud-only live data, plus the snapshot
The granules are HDF5 files in NSIDC's S3 bucket (Earthdata, AWS us-west-2).
The public titiler-cmr deployment cannot open them (tested: "file signature
not found"), so the live dataset (any 3-hour mean, calendar + time of day)
is read by this repository's [tiler](/tiler/) next to the data (preset
`smap-l4`, env.json `tiler`; it also needs a
[fix for SMAP's grouped HDF5](/tiler/fixes#grouped-hdf5)). It is cloud-only,
grayed out with a cloud icon when testing locally (unless pointed at a
tiler, see [local development](/build/local)). The pre-built 2026-07-30
snapshot stays in the menu and works locally.
:::

::: code-group
<<< @/../scripts/smap/website-layers.py#smap-live-source [scripts/smap/website-layers.py#smap-live-source]
:::

The date is the day after the CHIRPS storm below, when the soil should be
near its wettest. v008 is the current version.

::: code-group
<<< @/../scripts/smap/download.py#remote-hdf5-partial-read [scripts/smap/download.py#remote-hdf5-partial-read]
:::

::: warning Design decision: read the variable, not the file
The granule is a ~145 MB HDF5 file. `earthaccess.open` gives a file-like
object over HTTPS, and h5py reads from it only the blocks it needs: the
coordinates and `sm_rootzone`. That variable is one compressed chunk, so the
global field is transferred once and cropped in memory. The script checks
the file's coordinates against the nominal EASE-Grid 2.0 9 km transform
(to within 10 m), then writes a small GeoTIFF in EPSG:6933. `earthaccess` and
`h5py` are imported inside the function, so `visualize.py` can import
`download.py` for its paths without them.
:::

## CHIRPS

**CHIRPS v3.0 daily precipitation, 0.05°, 2026-07-29.** Scripts: `chirps.py`
(helpers), `find_rainy_days.py`, `download.py`, `visualize.py`,
`create-cog.py` (the pre-built snapshot, dataset `chirps-prebuilt`),
`website-layers.py` (the live, cloud-only dataset).

::: warning Design decision: live days through the tiler, plus the snapshot
The daily files are COGs, but the Climate Hazards Center serves them without
CORS headers, so the browser cannot read them. The live dataset (any day
from 2000 to about 45 days ago, when the "final" stream is published) is
read by the [tiler](/tiler/catalog#chirps) (preset `chirps-daily`, which
fills the day into the file's URL). Like SMAP it is cloud-only; the
pre-built 2026-07-29 snapshot works locally.
:::

::: code-group
<<< @/../scripts/chirps/website-layers.py#chirps-live-source [scripts/chirps/website-layers.py#chirps-live-source]
:::

::: code-group
<<< @/../scripts/chirps/chirps.py#chirps-urls-and-window [scripts/chirps/chirps.py#chirps-urls-and-window]
:::

- **Two streams.** Final daily files are COGs, so GDAL reads a small window
  over HTTP (`/vsicurl`) in one or two range requests. Preliminary files,
  for roughly the last month, are striped TIFFs that still read row by row.
- **Transform fix** <Badge type="danger" text="workaround" />: the files
  store a pixel size of 0.05000000074505806° (float32 rounding).
  `read_window` rebuilds the exact transform on the nominal 0.05° grid with
  origin (−180°, 60°), so pixel edges land where they should.
- `find_rainy_days.py` scans every day of 2026 in parallel and ranks days by
  rain at New Haven Green, printing the range across the view.
  2026-07-29 had ~40 mm at the Green and a clear west–east gradient (~50 to
  ~30 mm).

## VIIRS Black Marble

**VNP46A4 v002 annual composite for 2025, tile h10v04, near-nadir snow-free
radiance.** Scripts: `download.py`, `visualize.py`, `create-cog.py` (the
pre-built 2025 snapshot, dataset `viirs-nightlights-prebuilt`),
`website-layers.py` (the live, cloud-only dataset: any year; the public
titiler-cmr deployment has no S3 access to LAADS, so it is read by the same
[tiler](/tiler/catalog#blackmarble) as SMAP, preset `viirs-blackmarble`).

::: code-group
<<< @/../scripts/viirs-nightlights/website-layers.py#nightlights-live-source [scripts/viirs-nightlights/website-layers.py#nightlights-live-source]
:::

::: code-group
<<< @/../scripts/viirs-nightlights/download.py#cmr-temporal-quirk [scripts/viirs-nightlights/download.py#cmr-temporal-quirk]
:::

::: danger Workaround: search returns the previous year
The 2024 composite's time range ends on 2025-01-01, so a 2025 search also
returns it. Links are filtered by the `.A2025001.` token in the file name,
and the script asserts exactly one tile, h10v04.
:::

::: code-group
<<< @/../scripts/viirs-nightlights/visualize.py#hdfeos-grid-transform [scripts/viirs-nightlights/visualize.py#hdfeos-grid-transform]
:::

The HDF-EOS file gives its grid in a text metadata block, not as a
GeoTIFF transform. The transform is parsed from it and asserted against the
file's latitude/longitude arrays. Radiance is shown on a log scale
(0.5–200 nW cm⁻² sr⁻¹). The figures clip zero values over water up to the
minimum; the website relies on the colormap's "under" color for them.
