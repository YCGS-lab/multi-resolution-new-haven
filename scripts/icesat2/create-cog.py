# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas", "pyarrow", "shapely", "numpy", "pandas", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ICESat-2 canopy heights and sample lines (from download.py's files) as a COG
for the website, on a 2.5 m Web Mercator grid:

  canopy_recent, canopy_all   ATL08 h_canopy_20m (m) of each 20 m segment,
                              growing seasons 2025-2026 / 2019-2026, burned as
                              12 m discs (~ the 11 m laser footprint), most
                              recent pass on top
  ground_recent, ground_all   1 where a segment has a ground but no canopy height
                              (8 m discs)
  tracks                      sample line number (1-3) along the ATL03 ground
                              tracks of the photon profiles (12 m wide)

The website draws them over OpenStreetMap tiles (desaturated and lightened,
as in visualize.py), read directly from tile.openstreetmap.org, and grows
the footprints to a few screen pixels when zoomed out.

Products: canopy_height, canopy_height_allyears, tracks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from rasterio.features import rasterize
from shapely.geometry import LineString

from common import remote, web
from visualize import ALL_YEARS, CANOPY_CMAP, CANOPY_NORM, LINE_COLORS, NO_CANOPY, RECENT, load_20m, load_lines, pass_summary

PIXEL_M = 2.5
CANOPY_RADIUS_M = 6.0
GROUND_RADIUS_M = 4.0
TRACK_HALF_WIDTH_M = 6.0
# (the OpenStreetMap attribution comes with the basemap source)
DATA_SOURCE = "NASA ICESat-2 ATL08/ATL03 release 007 via SlideRule Earth (slideruleearth.io)"


def burn(shapes_values, grid) -> np.ndarray:
    shapes_values = list(shapes_values)
    if not shapes_values:
        return np.full(grid.shape, np.nan, dtype="float32")
    return rasterize(shapes_values, out_shape=grid.shape, transform=grid.transform, fill=np.nan, dtype="float32")


def segments(years, grid):
    """(canopy, ground-only) rasters and the GeoDataFrame of segments."""
    gdf = load_20m(years).to_crs(web.CRS)  # time-sorted: later passes are burned on top
    m = web.EXTENT_VIEW.merc_scale
    has = gdf["h_canopy_20m"].notna().values
    canopy = burn(zip(gdf.geometry[has].buffer(CANOPY_RADIUS_M * m, 8), gdf["h_canopy_20m"][has]), grid)
    ground = burn(((g, 1.0) for g in gdf.geometry[~has].buffer(GROUND_RADIUS_M * m, 8)), grid)
    print(f"  {years[0]}-{years[-1]}: {has.sum()} canopy + {(~has).sum()} ground-only segments")
    return canopy, ground, load_20m(years)


def main():
    grid = web.Grid(PIXEL_M)
    canopy_recent, ground_recent, gdf_recent = segments(RECENT, grid)
    canopy_all, ground_all, gdf_all = segments(ALL_YEARS, grid)
    lines = load_lines()
    m = web.EXTENT_VIEW.merc_scale
    track_shapes = []
    for line in lines:
        ph = line["photons"].iloc[::25].sort_values("dist_km").to_crs(web.CRS)
        track_shapes.append(
            (LineString(list(zip(ph.geometry.x, ph.geometry.y))).buffer(TRACK_HALF_WIDTH_M * m), float(line["n"]))
        )
    tracks = burn(track_shapes, grid)
    bands = ["canopy_recent", "ground_recent", "canopy_all", "ground_all", "tracks"]
    data = np.stack([canopy_recent, ground_recent, canopy_all, ground_all, tracks])
    sources = {
        "icesat2": web.write_cog("icesat2", data, grid, bands, max_z_error=0.01),
        "osm": web.xyz_source(remote.OSM_URL, max_zoom=19, attribution=remote.OSM_ATTRIBUTION),
    }
    basemap = web.layer("osm", web.identity(desaturate=0.55, lighten=0.35))

    products = {}
    for product, period, gdf, suffix in (
        ("canopy_height", "May-Sep 2025 and May-Sep 2026 (2026 data available through mid-July)", gdf_recent, "recent"),
        ("canopy_height_allyears", "Growing seasons (May-Sep) 2019-2026", gdf_all, "all"),
    ):
        n, dates = pass_summary(gdf, web.EXTENT_VIEW)
        when = ", ".join(dates) if len(dates) <= 6 else f"{dates[0]} to {dates[-1]}"
        products[product] = web.product(
            title="ICESat-2 ATL08 canopy height",
            subtitle=(
                f"{period}: {n} with data ({when})\n"
                "ATL08 h_canopy_20m (98th percentile canopy relief); gray = ground only (no canopy height)"
            ),
            native="20 m along-track segments, ~11 m footprints",
            source=DATA_SOURCE,
            layers=[
                basemap,
                web.layer("icesat2", web.categorical(f"ground_{suffix}", {1: NO_CANOPY}), dilate_px=2),
                web.layer(
                    "icesat2",
                    web.colormap(CANOPY_CMAP, CANOPY_NORM, "Canopy height (m)", band=f"canopy_{suffix}", extend="max"),
                    dilate_px=3,
                ),
            ],
        )
    products["tracks"] = web.product(
        title="ICESat-2 photon profile sample lines",
        subtitle="Strong-beam ATL03 ground tracks with ATL08 photon classes (see figures/icesat2/profile_<n>.png)",
        native="ATL03 photons every ~0.7 m along track, ~11 m footprint",
        source=DATA_SOURCE,
        legend=dict(
            entries=[(c, f"{l['n']}: {l['label']}") for l, c in zip(lines, LINE_COLORS)],
            title="Sample line: date (UTC), track, beam",
        ),
        layers=[
            basemap,
            web.layer("icesat2", web.categorical("tracks", {l["n"]: c for l, c in zip(lines, LINE_COLORS)}), dilate_px=2),
        ],
    )
    web.write_spec("icesat2", sources, products)


if __name__ == "__main__":
    main()
