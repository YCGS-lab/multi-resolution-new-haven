# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow"]
# ///
"""Write website/catalog.json: the image menu for the web viewer.

Reads website/image-data/<dataset>.json, written by each dataset's
create-cog.py (local COGs) or website-layers.py (image services the website
reads directly): the data sources, and per product the layers with their
render specs (band combinations, value ranges, colormaps) and the text
around the image (title, subtitle, colorbar or legend, source).

Products are grouped by the TREE below; products that exist but are not in
TREE are listed under "Other".

    uv run scripts/website/build_catalog.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config, render, web
from common.views import CRS, load_landmarks


def item(dataset: str, product: str, label: str, title: str | None = None) -> dict:
    """A menu entry: one product."""
    return dict(dataset=dataset, product=product, label=label, title=title or label)


def group(label: str, *children) -> dict:
    return dict(label=label, children=list(children))


# region tree
# Menu hierarchy. Labels are short (the menu shows them with their parents);
# the full title shown above the map comes from the product spec.
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
    group(
        "Street maps",
        item("streetmap", "osm", "OpenStreetMap"),
        item("streetmap", "esri", "Esri World Street Map"),
        item("streetmap", "usgs-topo", "USGS National Map topo"),
    ),
]
# endregion tree


# region load-and-resolve
def load_specs() -> tuple[dict, dict]:
    """Sources {"<dataset>/<name>": source} and products {"<dataset>/<product>": product}."""
    sources, products = {}, {}
    for path in sorted(web.WEB_DATA.glob("*.json")):
        spec = json.loads(path.read_text())
        ds = spec["dataset"]
        for name, s in spec["sources"].items():
            sources[f"{ds}/{name}"] = s
        for name, p in spec["products"].items():
            p["layers"] = [{**l, "source": f"{ds}/{l['source']}"} for l in p["layers"]]
            products[f"{ds}/{name}"] = p
    return sources, products


def resolve(node: dict, products: dict, seen: set) -> dict | None:
    """Attach products to items; drop items and groups with nothing to show."""
    if "children" in node:
        children = [c for c in (resolve(c, products, seen) for c in node["children"]) if c]
        return dict(label=node["label"], children=children) if children else None
    pid = f"{node['dataset']}/{node['product']}"
    seen.add(pid)
    if pid not in products:
        return None
    return dict(id=pid, label=node["label"], menu_title=node["title"], **products[pid])
# endregion load-and-resolve


def main():
    # region catalog-json
    sources, products = load_specs()
    seen = set()
    tree = [n for n in (resolve(g, products, seen) for g in TREE) if n]
    other = [resolve(item(*pid.split("/", 1), pid.replace("/", ": ")), products, seen) for pid in products if pid not in seen]
    if other:
        tree.append(dict(label="Other", children=other))

    v = web.EXTENT_VIEW
    catalog = dict(
        crs=CRS,
        extent=dict(title=v.title, bounds=list(v.bounds)),
        landmarks=[
            dict(name=l["name"], lon=l["lon"], lat=l["lat"], label_left=l["name"] in render._LABEL_LEFT) for l in load_landmarks()
        ],
        sources=sources,
        tree=tree,
    )
    out = config.REPO / "website" / "catalog.json"
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    # endregion catalog-json
    kinds = {}
    for s in sources.values():
        kinds[s["type"]] = kinds.get(s["type"], 0) + 1
    print(
        f"wrote {out.relative_to(config.REPO)}: {len(products)} products from {len(sources)} sources "
        f"({', '.join(f'{n} {k}' for k, n in sorted(kinds.items()))})"
    )
    missing = sorted({f"{n['dataset']}/{n['product']}" for n in _items(TREE)} - set(products))
    if missing:
        print(f"  not built yet (run the dataset's create-cog.py / website-layers.py): {', '.join(missing)}")


def _items(nodes):
    for n in nodes:
        if "children" in n:
            yield from _items(n["children"])
        else:
            yield n


if __name__ == "__main__":
    main()
