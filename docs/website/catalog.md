# Catalog and coordinates

`website/js/catalog.js` loads `catalog.json` (written by
[`build_catalog.py`](/pipeline/website-data#the-catalog)) and wraps it in a
`Catalog` object that the rest of the site queries.

## The Catalog class <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/catalog.js#catalog-class [website/js/catalog.js#catalog-class]
:::

The constructor walks the menu tree once:

- `items` maps a product id (`"landsat/truecolor"`) to the product. Each
  product gets two extra fields: `path`, the labels of its groups (shown in
  the picker button), and `parent`, its group.
- `order` lists the ids in menu order; the first one is the default image.
- `sibling(id, ±1)` steps through a product's group, wrapping around: the
  `[` / `]` keys and the arrow buttons use it.
- `colorbar(p)` and `attributions(p)` pull a product's key and credits from
  its layers.

`loadCatalog` fetches the file with `cache: "no-cache"`, so a rebuilt
catalog is picked up without a hard reload.

## Three coordinate systems <Badge type="warning" text="decision" />

The website uses three coordinate systems. Keeping them apart is the main
thing to understand when reading the map code.

| System | Units | Used by |
|---|---|---|
| **World** | Web Mercator meters from the center of the Greater New Haven extent, y up; `2^zoom` screen pixels per meter | the app's view state, pan/zoom limits, axes, scale bar, swipe position |
| **Longitude / latitude** | degrees | deck.gl's `MapView`; image-service tiles, landmarks, background, spy lens |
| **deck.gl common space** | Web Mercator scaled to 512 units around the world | deck.gl-raster's COG meshes, so the swipe clip bounds of COG layers |

::: code-group
<<< @/../website/js/catalog.js#world-coordinates [website/js/catalog.js#world-coordinates]
:::

::: warning Why world coordinates survive
Before the migration, deck.gl drew in world coordinates directly
(`OrthographicView`, one unit per meter), and all the view logic was written
in them. deck.gl-raster needs a geographic `MapView`. Rather than rewrite
the zoom limits, axes, scale bar and URL handling, the app keeps world
coordinates and converts at the boundary with deck.gl. Measuring from the
extent center also keeps the numbers small (kilometers rather than
thousands of kilometers), which suits the GPU's 32-bit arithmetic when
deck.gl draws world coordinates directly. See [Map views](./map-views).
:::

- `lngLatExtent` is the extent in degrees, for the `extent` of tile layers.
- `worldToCommon(v, axis)` converts a world x or y to common space, for
  clipping COG layers in the swipe comparison
  ([overlay props](./viewer-and-grid#comparison-props-per-coordinate-system)).
- The `R = 6378137` sphere is Web Mercator's; latitudes come from the
  inverse Mercator formula.
