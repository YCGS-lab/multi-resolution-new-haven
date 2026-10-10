# Glossary

Terms used across these docs, in alphabetical order.

### ArcGIS ImageServer

An Esri web service that serves raster data (here: orthophotos, NAIP, lidar,
3DEP). Its `exportImage` operation returns an image of any bounding box and
size, in any coordinate system. You can ask for rendered 8-bit images or for
raw values (for example float32 elevations as a TIFF). The pipeline and the
website both call it directly.

### Band

One layer of values in a raster: for example the red band of an image, or the
`elevation` and `hillshade` bands of the ASTER COG. Bands have names in this
project (`red`, `nir08`, `hh`, `lst`, ...) because render specs refer to them
by name.

### COG

**Cloud-Optimized GeoTIFF**: a GeoTIFF whose contents are laid out so that a
client can read just the part it needs with [HTTP range requests](#range-request).
The image is split into square **tiles** (512 × 512 pixels here), and the file
contains **overviews**: copies of the image at 1/2, 1/4, 1/8, ... of the
resolution. A client zoomed out reads a few tiles of a coarse overview; zoomed
in, a few tiles of the full-resolution image. See [cogeo.org](https://cogeo.org/).

### Colormap

A list of colors that values are mapped to: a value is first *normalized* to
0–1 between a minimum and maximum (linearly, or on a log scale), then looked
up in the list. Values below the minimum or above the maximum get the
colormap's *under* and *over* colors. Here colormaps come from matplotlib and
are stored in the render spec as 256 hex colors.

### CRS

**Coordinate reference system**: how coordinates map to places on the Earth.
Identified by EPSG codes: EPSG:4326 is longitude/latitude, EPSG:3857 is
[Web Mercator](#web-mercator), EPSG:32618 is UTM zone 18 N.

### deck.gl

A JavaScript library for drawing map layers with WebGL. A **layer** draws one
kind of thing (bitmaps, points, text, map tiles). A **view** places layers on
the screen; a **viewport** is a view at a given position and zoom. See
[deck.gl](https://deck.gl).

### deck.gl-raster

A library by Development Seed, built on deck.gl, that reads COGs and Zarr in
the browser and draws them on the GPU. Its `COGLayer` reads a COG's tiles and
draws each as a textured mesh, colored by a pipeline of [shader](#shader)
modules. Beta software (v0.8.1 here). See
[deck.gl-raster](https://github.com/developmentseed/deck.gl-raster).

### Footprint

The ground area one pixel of a dataset covers. This project keeps footprints
honest: a 2 km GOES pixel is drawn as a 2 × 3 km block, not a smooth blur.

### Fragment shader

See [shader](#shader).

### Granule

One file in a satellite data archive, usually one overpass or one tile. The
NASA search service ([CMR](https://cmr.earthdata.nasa.gov/)) returns granules.

### Hillshade

A grayscale image of a terrain model lit from one direction (here from the
northwest, 45° above the horizon), computed from the slope and aspect of
each pixel. It is used on its own, or multiplied into elevation colors as
*shading*.

### LERC

**Limited Error Raster Compression**: a lossy compression for floating-point
rasters in which every value is within a set maximum error of the original
(for example 0.01 °C). It is far smaller than lossless compression for real
measurements. Decoded in the browser by a WebAssembly module.

### Nearest-neighbor resampling

Giving each output pixel the value of the single input pixel at its center.
It is the only resampling that keeps coarse pixels as visible blocks with
sharp edges. *Average* resampling (the mean of the input pixels inside each
output pixel) is used when the input is finer than the output.

### No data

Pixels without a valid value: outside the data, under clouds, over water for
land-only products. Stored as NaN in memory, as −9999 in the float COGs, and
drawn transparent over a gray background.

### Overview

A reduced-resolution copy of an image inside a COG; see [COG](#cog).

### PEP 723

A Python standard for declaring a script's dependencies in a comment at its
top. `uv run script.py` reads it and runs the script in a matching cached
environment, so no shared virtual environment is needed. See
[PEP 723](https://peps.python.org/pep-0723/).

### Range request

An HTTP request for part of a file (`Range: bytes=1000-1999`), answered with
status 206 and just those bytes. COG readers depend on it. Python's built-in
`http.server` ignores it, so the project has its own `serve.py`.

### Render spec

This project's JSON description of how to turn a layer's values into colors:
which band or band expression, what value range, which colormap, whether to
shade. Written by the Python pipeline and applied by the website. See
[Website data and the catalog](/pipeline/website-data#render-specs).

### Shader

A small program that runs on the GPU. A **fragment shader** runs once per
screen pixel (fragment) of a drawn shape and computes its color. Written in
**GLSL**, the OpenGL Shading Language. A **texture** is an image (or array of
numbers) uploaded to the GPU that shaders can read.

### STAC

**SpatioTemporal Asset Catalog**: a standard JSON API for searching
satellite scenes by place, time and properties. Used here for Landsat
(Microsoft Planetary Computer and USGS).

### Swath

The strip of ground a polar-orbiting sensor images in one pass. Swath
("Level 2") data come with a latitude and longitude for every pixel instead
of a regular grid, so they cannot be reprojected with an affine transform.

### Tile

A square piece of a larger image. COGs store their pixels in tiles; map
services and deck.gl split the map into tiles indexed by zoom level `z` and
column/row `x`, `y` (**XYZ tiles**).

### Web Mercator

EPSG:3857, the projection of web maps. Coordinates are meters on a sphere
that are stretched away from the equator: at New Haven's latitude (41.3° N)
one Web Mercator meter is about 0.75 ground meters (1 / cos 41.3°). All of
this project's maps, figures and website COGs use it, so nothing is ever
reprojected in the browser.

### World coordinates

The website's own map coordinates: Web Mercator meters measured from the
center of the Greater New Haven extent, with `2^zoom` screen pixels per meter.
See [Map views](/website/map-views).

### XYZ tiles

See [tile](#tile).
