# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "geopandas", "pyogrio", "shapely"]
# ///
"""Connecticut 2023 high-resolution impervious surface polygons (Ecopia AI for
the CT GIS Office), rasterized onto the view grids (run download.py first).

Polygons are burned in at each view's pixel centers (rasterio.features.rasterize
with view.transform), so the figures show the vector data at the view's pixel
size. Products per view:
  - classes:    the 11 "Land" classes, categorical colors with a legend
  - impervious: binary impervious vs. not (unpaved sports grounds excluded)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
from matplotlib.colors import to_rgba
from rasterio.features import rasterize

from common import config, render
from common.views import VIEWS

DATASET = "ct-impervious-2023"
GPKG = config.DATA / DATASET / "impervious_2023_land.gpkg"
SOURCE = "CT 2023 Impervious Surface (Land), Ecopia AI for the CT GIS Office, geodata.ct.gov"
SUBTITLE = "Polygons mapped from 2023 imagery; rasterized at {:.1f} m/pixel"
BACKGROUND = "#f3f1ec"  # not impervious (light neutral)

# (CateTitle, label, color) in burn order: later classes are drawn on top
# (bridges over roads, buildings over everything).
CLASSES = [
    ("unpaved_sportsground", "Sports field, unpaved", "#b5d98b"),
    ("pavement", "Other pavement", "#9e9e9e"),
    ("parking", "Parking", "#f2a541"),
    ("driveway", "Driveway", "#f6d55c"),
    ("road", "Road", "#3b3b3b"),
    ("railway", "Railway", "#8e44ad"),
    ("sidewalk", "Sidewalk", "#e377c2"),
    ("paved_sport_ground", "Sports field, paved", "#2a9d8f"),
    ("swimming_pool", "Swimming pool", "#29b6f6"),
    ("bridge", "Bridge", "#8b4513"),
    ("building", "Building", "#c0392b"),
]
NOT_IMPERVIOUS = {"unpaved_sportsground"}  # mapped in the layer, but not paved
IMPERVIOUS_COLOR = "#2b2b2b"


def rgba_lut(colors: list[str]) -> np.ndarray:
    return np.array([np.round(np.array(to_rgba(c)) * 255) for c in colors], dtype="uint8")


def main():
    if not GPKG.exists():
        raise SystemExit(f"{GPKG.relative_to(config.REPO)} not found; run download.py first")
    gdf = gpd.read_file(GPKG, columns=["CateTitle"])
    codes = {name: i + 1 for i, (name, _, _) in enumerate(CLASSES)}
    unknown = sorted(set(gdf["CateTitle"]) - set(codes))
    if unknown:
        print(f"ignoring {(~gdf['CateTitle'].isin(codes)).sum()} features with unknown classes {unknown}")
    gdf = gdf[gdf["CateTitle"].isin(codes)]
    gdf = gdf.assign(code=gdf["CateTitle"].map(codes), order=gdf["CateTitle"].map(codes))
    gdf = gdf.sort_values("order", kind="stable")
    print(f"{len(gdf)} polygons")

    lut = rgba_lut([BACKGROUND] + [c for _, _, c in CLASSES])
    imperv_lut = rgba_lut([BACKGROUND, IMPERVIOUS_COLOR])
    is_imperv = np.array([False] + [n not in NOT_IMPERVIOUS for n, _, _ in CLASSES])
    # Legend lists buildings first (top-most class), then the rest.
    legend_entries = [(c, l) for _, l, c in reversed(CLASSES)] + [(BACKGROUND, "Not impervious")]

    for view in VIEWS.values():
        print(view.title)
        xmin, ymin, xmax, ymax = view.bounds
        sub = gdf.cx[xmin:xmax, ymin:ymax]
        grid = rasterize(
            zip(sub.geometry, sub["code"]),
            out_shape=view.shape,
            transform=view.transform,
            fill=0,
            dtype="uint8",
        )
        frac = is_imperv[grid].mean()
        print(f"  {len(sub)} polygons; {frac:.1%} of pixels impervious")
        subtitle = SUBTITLE.format(view.pixel_size_m)

        render.save_figures(
            lut[grid], view, DATASET, "classes",
            title="Connecticut 2023 impervious surface classes",
            subtitle=subtitle,
            legend=dict(entries=legend_entries, ncol=2),
            source=SOURCE,
        )  # fmt: skip
        render.save_figures(
            imperv_lut[is_imperv[grid].astype("uint8")], view, DATASET, "impervious",
            title="Connecticut 2023 impervious surface",
            subtitle=subtitle + f"; {frac:.0%} impervious",
            legend=dict(entries=[(IMPERVIOUS_COLOR, "Impervious"), (BACKGROUND, "Not impervious")]),
            source=SOURCE,
            landmark_color="yellow",
        )  # fmt: skip


if __name__ == "__main__":
    main()
