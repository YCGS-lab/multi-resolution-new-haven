# Views and grids

Every map in the project, both figures and website, sits on a
[Web Mercator](/guide/glossary#web-mercator) pixel grid that is fixed in
advance. This page covers those grids and how data are resampled onto them.
These are the project's most important design decisions, because they decide
what the reader sees: real native pixels, not smoothed images.

## The two views <Badge type="warning" text="decision" />

`scripts/common/views.py` defines two windows:

::: code-group
<<< @/../scripts/common/views.py#views [scripts/common/views.py#views]
:::

| View | Center | Height (ground) | Output | Pixel |
|---|---|---|---|---|
| `greater`: Greater New Haven | 41.3039, −72.9193 | 12.09 km | 3840 × 2160 | 5.6 m |
| `central`: Central New Haven and Yale | 41.3136, −72.9238 | 2.16 km | 3840 × 2160 | 1.0 m |

A view is given the way Google Maps URLs give one (`@lat,lon,<height>m`): a
center and the ground distance from the top to the bottom of the image. The
width follows from the 16:9 shape.

::: code-group
<<< @/../scripts/common/views.py#view-class [scripts/common/views.py#view-class]
:::

::: warning Design decision: one projection, fixed grids
- **Web Mercator (EPSG:3857) everywhere.** It is the projection of web maps,
  so the website never reprojects. The cost is a scale factor:
  `merc_scale = 1 / cos(lat)` Mercator meters per ground meter (1.33 here).
  Every conversion between "ground meters" and grid units goes through it.
  It is nearly constant across a 12 km view.
- **Fixed output size per view.** All figures of a view have the same
  3840 × 2160 pixels over the same bounds. They are pixel-aligned: you can
  flip between them, or difference them, without registration.
- **`bounds_in(crs, pad_m)`.** Data are subset in their own CRS to the view
  plus a pad of at least one native pixel. This keeps the pixels that straddle
  the edge, so they are cut off by the image frame rather than missing: "crop
  the image, not the data".
:::

## Resampling onto a view <Badge type="warning" text="decision" />

`render.reproject_to_view` puts any raster onto a view's grid with rasterio:

::: code-group
<<< @/../scripts/common/render.py#reproject-to-view [scripts/common/render.py#reproject-to-view]
:::

With `resampling="auto"` it compares the source's native pixel size, measured
near the view center by `native_pixel_size_m`, with the view's output pixel:

- **Source coarser than the output** (almost always): **nearest neighbor**.
  Each output pixel takes the value of the source pixel under its center, so
  a 750 m VIIRS pixel appears as a 134 × 134 block of identical 5.6 m pixels,
  with its true footprint and sharp edges.
- **Source finer than the output** (e.g. 0.3 m NAIP on the 5.6 m view):
  **average**, so the result is not aliased.

Categorical data (classes) must not be averaged; callers pass `"nearest"` or
`"mode"`.

::: warning Why never bilinear
Bilinear or cubic resampling would make a 9 km SMAP cell look like a smooth
field, which hides the very thing the project shows: how coarse each dataset
really is. Nearest neighbor is the only choice that keeps pixel footprints.
:::

## Grids for the website <Badge type="warning" text="decision" />

The website shows one extent, Greater New Haven, at any zoom, so its data
are stored on grids over that extent (`scripts/common/web.py`). A `Grid` is
defined by its ground pixel size at the extent center:

::: code-group
<<< @/../scripts/common/web.py#grid-class [scripts/common/web.py#grid-class]
:::

The grid's origin is snapped to a multiple of its pixel size, and it covers
the extent (plus optional padding). Two grids with the same pixel size are
therefore identical, whichever dataset made them.

### Fine grids for the website

Data coarser than 30 m (VIIRS, GOES, SMAP, CHIRPS, ERA5-Land, PRISM, ASTER)
are not stored at their native size:

::: code-group
<<< @/../scripts/common/web.py#fine-grid [scripts/common/web.py#fine-grid]
:::

::: warning Design decision: store coarse data on a ~30 m grid
A native GOES pixel (about 2.1 km east-west at New Haven) is stored as a
block of 29.7 m pixels (2108 m / 71), copied by nearest neighbor. Why not
store the 2 km grid itself? The source grids are in other projections
(geostationary, EASE-Grid, lon/lat). Reprojecting them onto a 2 km Web
Mercator grid would move pixel edges by up to 1 km. On a ~30 m grid each
native pixel keeps its footprint to within half a grid pixel (15 m), and
the website needs no reprojection.

**Cost:** larger files. LERC compresses runs of identical values very well,
so the cost is small (the GOES COG is under 0.1 MB).

**Choice of size:** the native size divided by the smallest integer that
brings it to 30 m or below. The grid is therefore as coarse as the 15 m
error budget allows, which keeps files small.
:::

The website's reprojection helper is a thin rasterio wrapper with
nearest-neighbor as the default:

::: code-group
<<< @/../scripts/common/web.py#web-reproject [scripts/common/web.py#web-reproject]
:::

Swath data (VIIRS LST), which have a latitude and longitude per pixel rather
than an affine grid, cannot use it. They go through pyresample instead; see
[Temperature](./datasets/temperature#viirs-lst).

## Related

- [Figures](./figures): coloring and drawing the resampled grids.
- [Map views](/website/map-views): how the website maps the same Web Mercator
  coordinates to the screen.
