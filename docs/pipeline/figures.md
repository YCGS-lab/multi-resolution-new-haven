# Figures

Each `visualize*.py` script writes two PNGs per product and view to
`figures/<dataset>/`:

- `<view>_<product>.png`: the data only, exactly 3840 × 2160 pixels, one
  file pixel per view pixel. Use it for comparisons and animations.
- `<view>_<product>_labeled.png`: the same image with a title block, scale
  bar, landmarks, colorbar or legend, and a source line, drawn with
  matplotlib.

The helpers are in `scripts/common/render.py`. Most of it is standard
matplotlib and numpy, so this page is brief.

## From values to colors <Badge type="tip" text="standard" />

The usual sequence in a script:

```python
grid = render.reproject_to_view(arr, transform, crs, view)   # NaN = no data
img = render.colorize(grid, "inferno", vmin, vmax)           # RGBA uint8
render.save_figures(img, view, "dataset", "product", title=..., colorbar=...)
```

- `colorize` applies a matplotlib colormap and [norm](/guide/glossary#colormap);
  NaN becomes transparent.
- `stretch` and `percentiles` give the linear (optionally gamma-corrected)
  stretches used for RGB composites. Limits are usually the 1st–99th or
  2nd–98th percentile.
- `to_rgba` turns a 3-band 0–1 array into RGBA. A pixel is transparent if any
  band is NaN.

::: warning Design decision: stretch limits from the larger view
Composite scripts (Landsat, NAIP, CT orthoimagery) compute percentile limits
once, on the Greater New Haven view or pooled over both views, and use them
for both views. The two views of a product then have the same colors for the
same values, at the cost of a less contrasty central view.
:::

## Hillshade

::: code-group
<<< @/../scripts/common/render.py#hillshade-and-blend [scripts/common/render.py#hillshade-and-blend]
:::

A standard hillshade: sun from the northwest (azimuth 315°) at 45°, with
slope and aspect from `numpy.gradient`. The pixel spacing must be in the
elevation's units (meters). Geographic grids (ASTER) convert degrees to
meters first. `blend_hillshade` multiplies it into the colors, as in a
shaded relief map. The browser has the same formula, for image services
whose shading is computed live: see [Image-service layers](/website/image-services#cpu-coloring).

## Labeled figures <Badge type="tip" text="standard" />

`save_figures` writes both files:

::: code-group
<<< @/../scripts/common/render.py#save-figures [scripts/common/render.py#save-figures]
:::

`map_figure` sizes a matplotlib figure so that its single axes covers exactly
the view at 200 dpi, one figure pixel per view pixel. Axes coordinates are
EPSG:3857, so landmarks and tracks can be drawn with `view.to_xy(lon, lat)`.
`add_labels` adds the title block, a scale bar of a round length (1, 2 or 5
× 10ⁿ m) about a fifth of the width, the landmarks from
`data/landmarks.json`, and a colorbar or legend. No-data pixels show the
gray `#d0d0d0`; the website uses the same gray.

A few scripts (VIIRS and GOES land surface temperature, ICESat-2) build
their labeled figures by hand. They add quality overlays (hatching, cloud
masks) or draw points and profiles. See their [dataset pages](./datasets/).

## Shared color scales <Badge type="warning" text="decision" />

::: code-group
<<< @/../scripts/common/styles.py [scripts/common/styles.py]
:::

Datasets measuring the same quantity use the same scale, so their figures
compare directly. Elevation (CT lidar, 3DEP, ASTER) uses 0–160 m in the
greater view and 0–50 m in the central view. It uses the land part of
matplotlib's `terrain`, so low land does not read as water, and light blue
below the range for hydro-flattened water. VIIRS and GOES land surface
temperature use 20–45 °C with `inferno`. The website uses the
greater-view elevation range at all zooms.
