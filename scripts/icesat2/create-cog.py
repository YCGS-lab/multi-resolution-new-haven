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

Also writes website/image-data/icesat2-profiles.json for the website's
ICESat-2 tab: the sample lines' ground tracks and their ATL03 photons with
ATL08 classes (the data of figures/icesat2/profile_<n>.png), from the same
downloaded files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import json

import numpy as np
from rasterio.features import rasterize
from shapely.geometry import LineString

from common import remote, web
from visualize import ALL_YEARS, CANOPY_CMAP, CANOPY_NORM, CLASSES, LINE_COLORS, NO_CANOPY, RECENT, load_20m, load_lines, pass_summary

# region burn-footprint-discs
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
# endregion burn-footprint-discs


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

    # region dilated-products
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
    # endregion dilated-products
    web.write_spec("icesat2", sources, products)
    write_profiles(lines)


# region profiles-json
TRACK_STEP_M = 10.0  # ground track vertices every 10 m along track


def write_profiles(lines):
    """website/image-data/icesat2-profiles.json: per sample line, the ground
    track (lon / lat every TRACK_STEP_M, with its along-track distance) and the
    photons (distance along track and height in decimeters, ATL08 class), plus
    the plot's height range (as in visualize.profile)."""
    out = []
    for line, color in zip(lines, LINE_COLORS):
        ph = line["photons"].sort_values("dist_km")
        d = ph["dist_km"].values * 1000
        h = ph["height"].values
        cls = ph["atl08_class"].values.astype(int)
        lon, lat = ph.geometry.x.values, ph.geometry.y.values
        signal = np.isin(cls, (1, 2, 3))
        ground = h[cls == 1]
        lo = float(np.percentile(ground, 0.5) - 15)
        hi = float(np.percentile(h[signal], 99.9) + 25)
        keep = (h > lo - 50) & (h < hi + 50)  # photons far outside the plotted range are left out
        bins = np.floor(d / TRACK_STEP_M).astype(int)
        track = []
        for b in np.unique(bins):
            m = bins == b
            track.append([round(float(lon[m].mean()), 6), round(float(lat[m].mean()), 6), round(float(d[m].mean()), 1)])
        strength = "strong" if line["spot"] in (1, 3, 5) else "weak"
        out.append(
            dict(
                n=line["n"],
                color=color,
                label=line["label"],
                time=str(ph.index.min())[:16],
                rgt=line["rgt"],
                cycle=line["cycle"],
                beam=line["beam"],
                spot=line["spot"],
                strength=strength,
                length_m=round(float(d.max()), 1),
                height_range=[round(lo, 1), round(hi, 1)],
                track=track,
                photons=dict(
                    dist_dm=np.round(d[keep] * 10).astype(int).tolist(),
                    height_dm=np.round(h[keep] * 10).astype(int).tolist(),
                    cls="".join(map(str, cls[keep])),
                ),
            )
        )
        print(f"  line {line['n']}: {keep.sum()} photons, {len(track)} track vertices")
    classes = [dict(code=c, label=l, color=col, order=o) for c, (l, col, o) in CLASSES.items()]
    path = web.WEB_DATA / "icesat2-profiles.json"
    data = dict(
        source=DATA_SOURCE,
        note="Distance along track from the southern edge of the Greater New Haven view",
        classes=classes,
        lines=out,
    )
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"  wrote {path.relative_to(web.config.REPO)} ({path.stat().st_size / 1e6:.1f} MB)")
# endregion profiles-json


if __name__ == "__main__":
    main()
