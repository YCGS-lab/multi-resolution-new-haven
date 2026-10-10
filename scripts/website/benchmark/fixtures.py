# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Test COGs for the website's COG renderer (website/js/cog.js) that need no
credentials: website/image-data/fixtures*.tif and fixtures.json.

Each product exercises a render path that the real datasets use but that may
not be built locally (they need Earthdata / Planet / CDS credentials):

  jpeg        NAIP 2023 at 4.8 m as a JPEG COG, shown as is   (like planet)
  dem         3DEP elevation at 30 m with a stored hillshade   (like aster-dem)
  dem_log     the same elevations on a log color scale         (like viirs-nightlights)
  classes     elevation classes as uint8, lossless DEFLATE     (like ct-impervious-2023)
  tracks      sparse synthetic "tracks" of points, grown by dilate_px, over a
              desaturated OpenStreetMap basemap                (like icesat2)
  expr        band expressions of the Landsat bands, if landsat.tif is built
                                                               (like nisar-gcov)

    uv run scripts/website/benchmark/fixtures.py
    uv run scripts/website/build_catalog.py
"""

import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import rasterio
from matplotlib.colors import LogNorm, Normalize

from common import remote, render, styles, web

DATASET = "fixtures"
NAIP = "https://cteco.uconn.edu/ctraster/rest/services/images/NAIP_2023/ImageServer"
DEP3 = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
CHUNK = 1500  # px per exportImage request


def export(service: str, grid: web.Grid, **params) -> np.ndarray:
    """(bands, h, w) from exportImage over the grid, in chunks."""
    sess = remote.session()
    out = None
    for r0 in range(0, grid.height, CHUNK):
        for c0 in range(0, grid.width, CHUNK):
            h, w = min(CHUNK, grid.height - r0), min(CHUNK, grid.width - c0)
            x0, y1 = grid.x0 + c0 * grid.res, grid.y1 - r0 * grid.res
            q = dict(
                bbox=f"{x0:.3f},{y1 - h * grid.res:.3f},{x0 + w * grid.res:.3f},{y1:.3f}",
                bboxSR=3857,
                imageSR=3857,
                size=f"{w},{h}",
                f="image",
                **params,
            )
            r = sess.get(f"{service}/exportImage", params=q, timeout=300)
            r.raise_for_status()
            with rasterio.open(io.BytesIO(r.content)) as ds:
                a = ds.read().astype("float32")
            if out is None:
                out = np.full((a.shape[0], grid.height, grid.width), np.nan, "float32")
            out[:, r0 : r0 + h, c0 : c0 + w] = a
    return out


# region sparse-tracks
def tracks(grid: web.Grid) -> tuple[np.ndarray, np.ndarray]:
    """Sparse points every 20 m along a few straight lines: (canopy, track number)."""
    rng = np.random.default_rng(0)
    canopy = np.full(grid.shape, np.nan, "float32")
    track = np.zeros(grid.shape, "float32")
    for n in range(1, 7):
        x0 = grid.x0 + grid.width * grid.res * n / 7
        angle = math.radians(rng.uniform(-12, 12))
        for d in np.arange(0, grid.height * grid.res, 20 * web.EXTENT_VIEW.merc_scale):
            x, y = x0 + d * math.sin(angle), grid.y1 - d * math.cos(angle)
            c, r = int((x - grid.x0) / grid.res), int((grid.y1 - y) / grid.res)
            if 0 <= c < grid.width and 0 <= r < grid.height:
                canopy[r, c] = rng.gamma(2.0, 6.0)
                track[r, c] = n
    return canopy, track
# endregion sparse-tracks


def main():
    sources, products = {}, {}

    grid = web.Grid(4.8)
    rgb = export(NAIP, grid, format="jpgpng", bandIds="0,1,2", interpolation="RSP_BilinearInterpolation")
    sources["jpeg"] = web.write_cog(f"{DATASET}-jpeg", rgb[:3], grid, ["r", "g", "b"], kind="jpeg")
    products["jpeg"] = web.product(title="Fixture: NAIP 2023 as a JPEG COG", native="4.8 m", layers=[web.layer("jpeg", web.identity())])

    grid = web.Grid(30.0)
    z = export(DEP3, grid, format="tiff", pixelType="F32", renderingRule=json.dumps({"rasterFunction": "None"}), noData=-9999)[0]
    z[z < -1000] = np.nan
    hs = np.where(np.isfinite(z), render.hillshade(z, grid.pixel_m), np.nan)
    sources["dem"] = web.write_cog(f"{DATASET}-dem", np.stack([z, hs]), grid, ["elevation", "hillshade"], max_z_error=0.002)
    products["dem"] = web.product(
        title="Fixture: 3DEP elevation with a stored hillshade",
        native="30 m",
        layers=[
            web.layer(
                "dem",
                web.colormap(
                    styles.ELEVATION_CMAP,
                    Normalize(*styles.ELEVATION_RANGE["greater"]),
                    "Elevation (m)",
                    band="elevation",
                    extend=styles.ELEVATION_EXTEND,
                    shade=dict(band="hillshade", strength=0.5, precomputed=True),
                ),
            )
        ],
    )
    products["dem_log"] = web.product(
        title="Fixture: elevation on a log scale",
        native="30 m",
        layers=[web.layer("dem", web.colormap("cividis", LogNorm(1, 200), "Elevation (m)", band="elevation", extend="min", gamma=1.5))],
    )
    classes = np.digitize(np.nan_to_num(z, nan=-1), [0, 10, 25, 50, 100]).astype("float32")
    sources["classes"] = web.write_cog(f"{DATASET}-classes", classes[None], grid, ["cls"], kind="categorical")
    colors = {1: "#2166ac", 2: "#67a9cf", 3: "#d1e5f0", 4: "#fddbc7", 5: "#b2182b"}
    products["classes"] = web.product(
        title="Fixture: elevation classes (uint8, DEFLATE)",
        native="30 m",
        legend=dict(entries=[(c, f"class {k}") for k, c in colors.items()]),
        layers=[web.layer("classes", web.categorical("cls", colors))],
    )

    grid = web.Grid(10.0)
    canopy, track = tracks(grid)
    sources["tracks"] = web.write_cog(f"{DATASET}-tracks", np.stack([canopy, track]), grid, ["canopy", "track"], max_z_error=0.01)
    sources["osm"] = web.xyz_source(remote.OSM_URL, max_zoom=19, attribution=remote.OSM_ATTRIBUTION)
    products["tracks"] = web.product(
        title="Fixture: sparse points grown by dilate_px over a basemap",
        native="10 m",
        layers=[
            web.layer("osm", web.identity(desaturate=0.55, lighten=0.35)),
            web.layer("tracks", web.categorical("track", {n: "#7f7f7f" for n in range(1, 7)}), dilate_px=2),
            web.layer("tracks", web.colormap("viridis", Normalize(0, 30), "Canopy height (m)", band="canopy", extend="max"), dilate_px=3),
        ],
    )

    landsat = web.WEB_DATA / "landsat.json"
    if landsat.exists():
        sources["landsat"] = json.loads(landsat.read_text())["sources"]["l2"]
        products["expr"] = web.product(
            title="Fixture: band expressions (NDVI, NIR / red in dB, SWIR)",
            native="30 m",
            layers=[
                web.layer(
                    "landsat",
                    web.rgb(
                        web.channel(expr="(nir08 - red) / (nir08 + red)", lo=-0.2, hi=0.9),
                        web.channel(expr="10 * log10(max(nir08, 1e-4) / max(red, 1e-4))", lo=-3, hi=15, gamma=1.2),
                        web.channel(expr="swir16", lo=0.0, hi=0.4),
                    )
                ),
            ],
        )
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
