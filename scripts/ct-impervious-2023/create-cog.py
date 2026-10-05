# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas", "pyogrio", "numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""Connecticut 2023 impervious surface polygons as a COG for the website: band
class (uint8 codes of visualize.CLASSES, 0 = not impervious), rasterized at
pixel centers on a 0.5 m Web Mercator grid, in visualize.py's burn order.
Lossless (DEFLATE), with mode-resampled overviews.

Products: classes (categorical colors), impervious (impervious / not).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine

from common import config, web
from visualize import BACKGROUND, CLASSES, DATASET, GPKG, IMPERVIOUS_COLOR, NOT_IMPERVIOUS, SOURCE

PIXEL_M = 0.5
STRIP = 2048  # rows rasterized at a time


def main():
    if not GPKG.exists():
        raise SystemExit(f"{GPKG.relative_to(config.REPO)} not found; run download.py first")
    grid = web.Grid(PIXEL_M)
    gdf = gpd.read_file(GPKG, columns=["CateTitle"], bbox=grid.bounds_in(gpd.read_file(GPKG, rows=1).crs))
    codes = {name: i + 1 for i, (name, _, _) in enumerate(CLASSES)}
    gdf = gdf[gdf["CateTitle"].isin(codes)].to_crs(web.CRS)
    gdf = gdf.assign(code=gdf["CateTitle"].map(codes)).sort_values("code", kind="stable")
    print(f"{len(gdf)} polygons; rasterizing onto {grid}")
    out = np.zeros(grid.shape, dtype="uint8")
    t = grid.transform
    for r0 in range(0, grid.height, STRIP):
        h = min(STRIP, grid.height - r0)
        y1 = t.f + r0 * t.e
        y0 = y1 + h * t.e
        sub = gdf.cx[:, y0:y1]
        if len(sub):
            out[r0 : r0 + h] = rasterize(
                zip(sub.geometry, sub["code"]),
                out_shape=(h, grid.width),
                transform=t * Affine.translation(0, r0),
                fill=0,
                dtype="uint8",
            )
    is_imperv = np.array([False] + [n not in NOT_IMPERVIOUS for n, _, _ in CLASSES])
    frac = is_imperv[out].mean()
    print(f"{frac:.1%} of pixels impervious")
    sources = {"classes": web.write_cog(DATASET, out[None], grid, ["cls"], kind="categorical", nodata=None)}

    subtitle = "Polygons mapped from 2023 imagery"
    native = f"vector polygons, rasterized at {PIXEL_M} m"
    class_colors = {0: BACKGROUND} | {i + 1: c for i, (_, _, c) in enumerate(CLASSES)}
    imperv_colors = {code: IMPERVIOUS_COLOR if is_imperv[code] else BACKGROUND for code in class_colors}
    products = {
        "classes": web.product(
            title="Connecticut 2023 impervious surface classes",
            subtitle=subtitle,
            native=native,
            source=SOURCE,
            legend=dict(entries=[(c, l) for _, l, c in reversed(CLASSES)] + [(BACKGROUND, "Not impervious")], ncol=2),
            layers=[web.layer("classes", web.categorical("cls", class_colors))],
        ),
        "impervious": web.product(
            title="Connecticut 2023 impervious surface",
            subtitle=f"{subtitle}; {frac:.0%} of the extent impervious",
            native=native,
            source=SOURCE,
            landmark_color="yellow",
            legend=dict(entries=[(IMPERVIOUS_COLOR, "Impervious"), (BACKGROUND, "Not impervious")]),
            layers=[web.layer("classes", web.categorical("cls", imperv_colors))],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
