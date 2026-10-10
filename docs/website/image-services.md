# Image-service layers

`website/js/tiles.js` turns a product into deck.gl layers, and implements the
two kinds of layer that read live services: ArcGIS ImageServers and XYZ map
tiles.

## One deck.gl layer per product layer <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/tiles.js#product-layers [website/js/tiles.js#product-layers]
:::

Layer ids combine the map slot, the product and the layer index
(`a-landsat/truecolor-0`). Switching products therefore creates new layers
and new tiles; deck.gl drops the old ones. `props(kind)` supplies the
comparison settings in the coordinates each kind of layer uses: `"common"`
for COG layers, `"lnglat"` for the rest. See
[comparison props](./viewer-and-grid#comparison-props-per-coordinate-system).

## ArcGIS ImageServers

Used by the CT orthoimagery, NAIP, CT lidar and 3DEP. A deck.gl `TileLayer`
splits the map into 512 × 512-pixel Web Mercator tiles. For each tile it
asks the service for exactly that box, colors the result on the CPU, and
draws it as a bitmap.

::: code-group
<<< @/../website/js/tiles.js#arcgis-layer [website/js/tiles.js#arcgis-layer]
:::

- **Tile size and zoom.** 512-pixel tiles, one zoom level finer on high-DPI
  screens (`zoomOffset`), so a tile pixel is about one device pixel. The
  deepest tile zoom is where tile pixels match the source's native size.
  Beyond it, tiles are scaled up (nearest neighbor), not re-requested.
- **Bitmaps** are drawn with nearest-neighbor filtering, so native pixels
  stay sharp blocks.
- **`maxRequests: 8`** concurrent tile loads, as before the migration.

::: code-group
<<< @/../website/js/tiles.js#arcgis-request [website/js/tiles.js#arcgis-request]
:::

The request mirrors the Python [`arcgis_export_image`](/pipeline/remote#arcgis-exportimage-and-wms):

- **Raw sources** (DEMs): a float32 TIFF with rendering rule `None`. Values
  are multiplied by the source's `scale` (feet → meters), and `nodata` and
  the service's huge negative fill values become NaN.
- **Imagery**: `format=jpgpng`, the server's 8-bit rendering. It uses
  nearest-neighbor interpolation near native resolution, so pixels are true,
  and bilinear when zoomed out, so the image is smooth.

A failed tile is retried once. The services occasionally send a truncated
image.

::: code-group
<<< @/../website/js/tiles.js#read-float-tiff [website/js/tiles.js#read-float-tiff]
:::

::: danger Workaround: sparse TIFF tiles
ArcGIS writes float TIFFs whose tiles without data have a byte count of 0
("sparse" tiles). The old code had a hand-written reader for them, because
geotiff.js could not read them. Now the bundled `@developmentseed/geotiff`
reads each internal tile. A sparse tile raises "not found", which is caught
and left as NaN.
:::

### CPU coloring

::: code-group
<<< @/../website/js/tiles.js#render-arcgis-tile [website/js/tiles.js#render-arcgis-tile]
<<< @/../website/js/tiles.js#cpu-colorize [website/js/tiles.js#cpu-colorize]
<<< @/../website/js/tiles.js#cpu-hillshade [website/js/tiles.js#cpu-hillshade]
:::

This is the old renderer's coloring code, kept for ArcGIS tiles. It applies
the [render spec](/pipeline/website-data#render-specs) pixel by pixel in
JavaScript: expressions (compiled once with `new Function`), stretches,
colormaps, categorical tables, and hillshades.

::: warning Design decision: hillshades need a one-pixel border
A hillshade needs each pixel's neighbors. When the spec computes one
(`hillshade` or `shade` without `precomputed`), the tile is requested one
pixel larger on each side (`pad = 1`). The border is cropped after coloring.
Shading is then seamless across tile edges.
:::

::: warning Not migrated: GPU coloring for ArcGIS tiles
These tiles are still colored on the main thread. They could use
deck.gl-raster's `RasterTileLayer` and the same generated shaders as COGs.
The obstacle is the hillshade border: `RasterTileLayer` maps each tile's
texture edge to edge, with no way to sample a margin around it. The CPU
code is thus a second implementation of the render specs; any change to the
specs must be made in both.
:::

## XYZ map tiles

The street maps and the ICESat-2 basemap.

::: code-group
<<< @/../website/js/tiles.js#xyz-layers [website/js/tiles.js#xyz-layers]
:::

A plain deck.gl `TileLayer` with the tile URL template. deck.gl loads each
tile image itself. With `tileSize: 256` the tiles are drawn at roughly their
design size (256 CSS pixels), so the labels stay readable at every zoom.
They are scaled smoothly, since they contain text. `desaturate` is
`BitmapLayer`'s own option. Lightening (`255 − (1 − l)(255 − v)`) is the
same as a white layer of opacity `l` on top, which is how it is drawn.

::: tip Standard practice
This is how deck.gl's documentation draws raster map tiles. The old
renderer instead fetched tiles into a canvas mosaic, cropped it, resampled
it and colored it per tile. See [Basemaps and services](/comparison/services).
:::
