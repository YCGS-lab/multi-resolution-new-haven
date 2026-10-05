# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""Write website/catalog.json: the image menu for the web viewer.

Scans figures/<dataset>/<view>_<product>.png (the unlabeled figures) and their
<view>_<product>.json sidecars (titles, colorbars, legends; written by
render.save_figures). Figures without a sidecar (rendered before sidecars
existed) are still listed, with the fallback title below and no colorbar;
re-run the dataset's visualize script to get the full labels.

Images are grouped by the TREE below. Figures that exist but are not in TREE
are listed under "Other".

    uv run scripts/website/build_catalog.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, render
from common.views import CRS, VIEWS, load_landmarks

WEBSITE = config.REPO / "website"


def item(dataset: str, product: str, label: str, title: str | None = None) -> dict:
    """A menu entry: one product, available in one or more views."""
    return dict(dataset=dataset, product=product, label=label, title=title or label)


def group(label: str, *children) -> dict:
    return dict(label=label, children=list(children))


# Menu hierarchy. Labels are short (the menu shows them with their parents);
# the full title shown above the map comes from the figure's sidecar.
TREE = [
    group(
        "Optical imagery",
        group(
            "True color",
            item("ct-ortho-2023", "truecolor", "CT orthoimagery 2023 (7.6 cm)", "Connecticut 2023 orthoimagery, true color"),
            item("naip", "truecolor", "NAIP 2023 (0.3 m)", "NAIP 2023, true color"),
            item("planet", "truecolor", "Planet basemap, July 2026 (4.8 m)", "Planet monthly basemap, true color"),
            item("landsat", "truecolor", "Landsat 8, 2024-08-27 (30 m)", "Landsat 8 true color"),
        ),
        group(
            "Color infrared",
            item("ct-ortho-2023", "cir", "CT orthoimagery 2023 (7.6 cm)", "Connecticut 2023 orthoimagery, color infrared"),
            item("naip", "cir", "NAIP 2023 (0.3 m)", "NAIP 2023, color infrared"),
            item("landsat", "cir", "Landsat 8 (30 m)", "Landsat 8 color infrared"),
        ),
        group(
            "Landsat 8, 2024-08-27",
            item("landsat", "pan", "Panchromatic (15 m)", "Landsat 8 panchromatic (OLI band 8)"),
            item("landsat", "veg", "False color: vegetation", "Landsat 8 false color (vegetation)"),
            item("landsat", "urban", "False color: urban", "Landsat 8 false color (urban)"),
        ),
    ),
    group(
        "Temperature",
        group(
            "Land surface temperature",
            item("landsat", "lst", "Landsat 8, 2024-08-27 (100 m)", "Landsat 8 land surface temperature"),
            item("viirs-lst", "lst", "VIIRS, 2026-06-03 (750 m)", "VIIRS land surface temperature (750 m)"),
            item("goes-lst", "lst", "GOES-19 ABI, 2026-06-03 (2 km)", "GOES-19 ABI land surface temperature (2 km)"),
        ),
        group(
            "Air temperature",
            group(
                "ERA5-Land 2 m, 2026-07-20 (0.1°)",
                item("era5-land", "t2m_sunrise", "Sunrise", "ERA5-Land 2 m air temperature, sunrise"),
                item("era5-land", "t2m_midday", "Solar noon", "ERA5-Land 2 m air temperature, solar noon"),
                item("era5-land", "t2m_sunset", "Sunset", "ERA5-Land 2 m air temperature, sunset"),
                item("era5-land", "t2m_night", "Middle of the night", "ERA5-Land 2 m air temperature, middle of the night"),
            ),
            item("prism", "tmean", "PRISM July 2026 mean (800 m)", "PRISM mean air temperature"),
        ),
    ),
    group(
        "Elevation",
        group(
            "Bare-earth elevation",
            item("ct-lidar-2023", "elevation", "CT lidar 2023 (0.6 m)", "Connecticut 2023 lidar elevation (bare earth)"),
            item("3dep", "elevation", "USGS 3DEP (~1 m)", "USGS 3DEP elevation"),
            item("aster-dem", "elevation", "ASTER GDEM v3 (30 m)", "ASTER GDEM v3 elevation"),
        ),
        group(
            "Hillshade",
            item("ct-lidar-2023", "hillshade", "CT lidar 2023 (0.6 m)", "Connecticut 2023 lidar hillshade (bare earth)"),
            item("3dep", "hillshade", "USGS 3DEP (~1 m)", "USGS 3DEP hillshade"),
            item("aster-dem", "hillshade", "ASTER GDEM v3 (30 m)", "ASTER GDEM v3 hillshade"),
        ),
        item("ct-lidar-2023", "surface", "Surface elevation: CT lidar 2023 (0.9 m)", "Connecticut 2023 lidar surface elevation"),
    ),
    group(
        "Vegetation and land cover",
        group(
            "ICESat-2 canopy height",
            item("icesat2", "canopy_height", "May-Sep 2025-2026", "ICESat-2 ATL08 canopy height"),
            item("icesat2", "canopy_height_allyears", "Growing seasons 2019-2026", "ICESat-2 ATL08 canopy height"),
            item("icesat2", "tracks", "Photon profile sample lines", "ICESat-2 photon profile sample lines"),
        ),
        group(
            "CT impervious surface 2023",
            item("ct-impervious-2023", "classes", "Classes", "Connecticut 2023 impervious surface classes"),
            item("ct-impervious-2023", "impervious", "Impervious / not", "Connecticut 2023 impervious surface"),
        ),
    ),
    group(
        "Radar: NISAR L-band SAR, 2026-07-17",
        group(
            "Dual-pol composites",
            item("nisar-gcov", "balanced", "Balanced", "NISAR L-band SAR: balanced dual-pol RGB"),
            item("nisar-gcov", "vegetation", "Vegetation emphasis", "NISAR L-band SAR: vegetation / volume emphasis"),
            item("nisar-gcov", "urban", "Urban emphasis", "NISAR L-band SAR: urban / built structure emphasis"),
            item("nisar-gcov", "water", "Water emphasis", "NISAR L-band SAR: water / smooth surface emphasis"),
        ),
        group(
            "Single polarization",
            item("nisar-gcov", "hh", "HH backscatter", "NISAR L-band SAR: HH backscatter"),
            item("nisar-gcov", "hv", "HV backscatter", "NISAR L-band SAR: HV backscatter"),
        ),
    ),
    group(
        "Water",
        item("smap", "sm_rootzone", "SMAP root-zone soil moisture (9 km)", "SMAP L4 root-zone soil moisture (0-100 cm)"),
        item("chirps", "precip", "CHIRPS daily precipitation (0.05°)", "CHIRPS v3 daily precipitation"),
    ),
    group(
        "Night lights",
        item("viirs-nightlights", "radiance", "VIIRS Black Marble 2025 (500 m)", "VIIRS Black Marble night lights"),
    ),
]


def view_meta(view) -> dict:
    return dict(
        title=view.title,
        bounds=list(view.bounds),
        width=view.width_px,
        height=view.height_px,
        pixel_size_m=view.pixel_size_m,
    )


def find_images(dataset: str, product: str) -> dict:
    """{view name: image entry} for the figures of one product that exist."""
    images = {}
    for view in VIEWS.values():
        png = config.FIGURES / dataset / f"{view.name}_{product}.png"
        if not png.exists():
            continue
        sidecar = png.with_suffix(".json")
        meta = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        meta["src"] = os.path.relpath(png, WEBSITE).replace(os.sep, "/")
        meta.setdefault("bounds", list(view.bounds))
        labeled = png.with_name(f"{png.stem}_labeled.png")
        if labeled.exists():
            meta["labeled"] = os.path.relpath(labeled, WEBSITE).replace(os.sep, "/")
        images[view.name] = meta
    return images


def resolve(node: dict, seen: set) -> dict | None:
    """Attach images to items; drop items and groups with nothing to show."""
    if "children" in node:
        children = [c for c in (resolve(c, seen) for c in node["children"]) if c]
        return dict(label=node["label"], children=children) if children else None
    seen.add((node["dataset"], node["product"]))
    images = find_images(node["dataset"], node["product"])
    if not images:
        return None
    return dict(
        id=f"{node['dataset']}/{node['product']}",
        label=node["label"],
        title=node["title"],
        images=images,
    )


def unlisted(seen: set) -> list[dict]:
    """Map figures on disk that TREE does not mention."""
    out = []
    for png in sorted(config.FIGURES.glob("*/*.png")):
        view, _, product = png.stem.partition("_")
        if view not in VIEWS or product.endswith("_labeled") or (png.parent.name, product) in seen:
            continue
        seen.add((png.parent.name, product))
        out.append(item(png.parent.name, product, f"{png.parent.name}: {product}"))
    return out


def main():
    seen = set()
    tree = [n for n in (resolve(g, seen) for g in TREE) if n]
    other = [n for n in (resolve(i, seen) for i in unlisted(seen)) if n]
    if other:
        tree.append(dict(label="Other", children=other))

    n_items = n_images = n_sidecars = 0

    def count(node):
        nonlocal n_items, n_images, n_sidecars
        for c in node.get("children", []):
            count(c)
        if "images" in node:
            n_items += 1
            n_images += len(node["images"])
            n_sidecars += sum("title" in m for m in node["images"].values())

    for node in tree:
        count(node)

    catalog = dict(
        crs=CRS,
        extent="greater",
        views={name: view_meta(v) for name, v in VIEWS.items()},
        landmarks=[
            dict(name=l["name"], lon=l["lon"], lat=l["lat"], label_left=l["name"] in render._LABEL_LEFT)
            for l in load_landmarks()
        ],
        tree=tree,
    )
    out = WEBSITE / "catalog.json"
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out.relative_to(config.REPO)}: {n_items} products, {n_images} images ({n_sidecars} with labels)")
    if n_sidecars < n_images:
        print("  images without a .json sidecar get a fallback title and no colorbar or legend; re-run their visualize script")


if __name__ == "__main__":
    main()
