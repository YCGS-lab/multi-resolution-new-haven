# Remote services

`scripts/common/remote.py` fetches imagery from web services straight onto a
view's grid. The figures of the image-service datasets (CT orthoimagery,
NAIP, CT lidar, 3DEP, Planet), the ICESat-2 basemap and the Landsat Level-2
bands use it.

## HTTP session <Badge type="tip" text="standard" />

::: code-group
<<< @/../scripts/common/remote.py#session [scripts/common/remote.py#session]
:::

A `requests` session that retries up to five times with exponential backoff
on rate limits (429) and server errors (5xx), and identifies the project in
its `User-Agent`, as tile providers such as OpenStreetMap ask.

## XYZ tiles

::: code-group
<<< @/../scripts/common/remote.py#fetch-xyz [scripts/common/remote.py#fetch-xyz]
:::

It picks the coarsest zoom whose tile pixels are at least as fine as the
view's (`auto_zoom`). It downloads the tiles covering the view in parallel,
mosaics them, and resamples the mosaic onto the view grid. Missing tiles
(404) stay transparent. Tiles and views are both Web Mercator, so the
resampling only scales.

## ArcGIS `exportImage` and WMS <Badge type="warning" text="decision" />

::: code-group
<<< @/../scripts/common/remote.py#arcgis-export-image [scripts/common/remote.py#arcgis-export-image]
:::

::: code-group
<<< @/../scripts/common/remote.py#fetch-chunks [scripts/common/remote.py#fetch-chunks]
:::

[ArcGIS ImageServers](/guide/glossary#arcgis-imageserver) can render any box
at any size, so the view is requested directly in EPSG:3857, at its own pixel
size. Two details matter:

- **Chunks.** A full 3840 × 2160 request often times out (HTTP 504). The view
  is split into windows of at most 1024 px, fetched in parallel, and checked
  to have exactly the requested size before being assembled.
- **Raw values.** `fmt="tiff"`, `pixel_type="F32"` and
  `rendering_rule={"rasterFunction": "None"}` return the stored values
  (elevations in feet or meters) instead of a rendered image. The DEM
  figures need those values to compute their own hillshades.

Image datasets ask for twice the pixel density and average 2 × 2 blocks
(`OVERSAMPLE = 2` in the NAIP and CT orthoimagery scripts). The server reads
its own overviews with bilinear interpolation, and oversampling avoids the
resulting aliasing; see [Optical imagery](./datasets/optical#naip).

`wms_getmap` is the same chunked pattern for OGC WMS 1.3.0 GetMap, with NASA
GIBS as the predefined endpoint (`GIBS_WMS`). No script calls it at present.

::: tip Same services in the browser
The website calls the same ArcGIS `exportImage` endpoint itself, tile by
tile, with the same raw-value parameters. See
[Image-service layers](/website/image-services).
:::
