# Elevation

Three terrain models: Connecticut's 2023 lidar (0.6 m), USGS 3DEP (~1 m) and
ASTER GDEM (~30 m). Each is shown as tinted elevation with shading and as a
gray hillshade. All three use the shared elevation scale in
[`styles.py`](../figures#shared-color-scales).

The two lidar-based models are read live from ArcGIS ImageServers, as raw
float32 elevations; the browser colors and shades them. ASTER is a local
COG with its hillshade stored as a second band.

## CT lidar 2023

**Bare-earth DEM, 2 ft (0.6 m), and maximum-surface DSM, 4 ft Mercator
(~0.9 m ground), spring 2023.** Scripts: `visualize-remote.py`,
`website-layers.py`.

Two CT ECO services:
- `Statewide2023`: the bare-earth digital elevation model (DEM), in the state
  plane CRS, US survey feet, NAVD88.
- `MaxSurfaceHeight_2023`: the digital surface model (DSM), the highest
  return, including buildings and trees. It is an absolute elevation, not a
  height above ground, published in Web Mercator.

::: code-group
<<< @/../scripts/ct-lidar-2023/website-layers.py#raw-float-scaled-sources [scripts/ct-lidar-2023/website-layers.py#raw-float-scaled-sources]
:::

::: warning Design decision: convert units in the browser
The services return US survey feet. The website source has `raw=True` with
`scale=FT_US` (1200/3937, exact), so the browser multiplies each value as it
reads it. The meter-based shared range then applies. The figures do the
same conversion in Python. `hillshade=True` and `shade` make the browser
compute hillshades from the elevations, because the services have none.
:::

## USGS 3DEP

**Best-available DEM (~1 m lidar-derived here), USGS 3DEPElevation
ImageServer.** Scripts: `visualize-remote.py`, `website-layers.py`. The same
pattern as the CT lidar, already in meters. `native_m=1.0` is assumed for
"best available", which caps the website's zoom.

## ASTER GDEM

**ASTGTM v003, 1″ (~30 m), 2000–2013.** Scripts: `download.py`,
`visualize.py`, `create-cog.py`.

`download.py` finds the 1° tiles covering the views through NASA's search
(two, since the area straddles 73° W) and downloads only the `_dem.tif`
files, skipping the quality layer. `visualize.py` merges them and computes
the hillshade on the native geographic grid. Pixel spacing in meters comes
from degrees × 111 320 × cos(lat) east-west and × 110 574 north-south.

::: code-group
<<< @/../scripts/aster-dem/create-cog.py#stored-hillshade-band [scripts/aster-dem/create-cog.py#stored-hillshade-band]
:::

::: warning Design decision: a stored hillshade band
ASTER's hillshade is computed once, on the native ~30 m grid, and stored as
a second band of the COG (`shade=dict(..., precomputed=True)` in the render
spec). Shading then follows the native pixels, and the browser's GPU path
needs no neighbor access. The browser computes hillshades only for the
ArcGIS DEMs, on the CPU; see [COG layers](/website/cog-layers#what-is-not-supported).
:::
