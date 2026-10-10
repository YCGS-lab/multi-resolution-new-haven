# Water and night lights

Three coarse datasets: SMAP soil moisture (9 km), CHIRPS precipitation
(0.05°, ~5 km) and VIIRS Black Marble night lights (~400 m). Their scripts
are short and mostly follow the shared pattern. The interesting parts are
in how each download reads only what it needs.

## SMAP

**SPL4SMGP v008 root-zone soil moisture, 9 km EASE-Grid 2.0, 2026-07-30
15:00–18:00 UTC.** Scripts: `download.py`, `visualize.py`, `create-cog.py`.

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
`create-cog.py`.

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
radiance.** Scripts: `download.py`, `visualize.py`, `create-cog.py`.

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
