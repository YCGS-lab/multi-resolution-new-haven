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
import re
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
            item("ct-ortho", "truecolor", "CT orthoimagery, 1934-2023 (7.6 cm-1 m)", "Connecticut orthoimagery, true color"),
            item("naip", "truecolor", "NAIP (0.3-1 m)", "NAIP, true color"),
            item("planet", "truecolor", "Planet monthly basemap (4.8 m)", "Planet monthly basemap, true color"),
            item("landsat", "truecolor", "Landsat 8-9 (30 m)", "Landsat 8-9 true color"),
        ),
        group(
            "Color infrared",
            item("ct-ortho", "cir", "CT orthoimagery, 2012-2023 (7.6-30 cm)", "Connecticut orthoimagery, color infrared"),
            item("naip", "cir", "NAIP (0.3-1 m)", "NAIP, color infrared"),
            item("landsat", "cir", "Landsat 8-9 (30 m)", "Landsat 8-9 color infrared"),
        ),
        group(
            "Landsat 8-9",
            item("landsat", "veg", "False color: vegetation", "Landsat 8-9 false color (vegetation)"),
            item("landsat", "urban", "False color: urban", "Landsat 8-9 false color (urban)"),
            item("landsat-pan", "pan", "Panchromatic, 2024-08-27 (15 m)", "Landsat 8 panchromatic (OLI band 8)"),
        ),
    ),
    group(
        "Temperature",
        group(
            "Land surface temperature",
            item("landsat", "lst", "Landsat 8-9 (100 m)", "Landsat 8-9 land surface temperature"),
            item("viirs-lst", "lst", "VIIRS, 2026-06-03 (750 m)", "VIIRS land surface temperature (750 m)"),
            item("goes-lst", "lst", "GOES-19 ABI, hourly (2 km)", "GOES-19 ABI land surface temperature (2 km)"),
            item("goes-lst-prebuilt", "lst", "GOES-19 ABI, 2026-06-03 (2 km, pre-built)", "GOES-19 ABI land surface temperature (2 km)"),
        ),
        group(
            "Air temperature",
            item("era5-land", "t2m", "ERA5-Land 2 m, hourly (0.1°)", "ERA5-Land 2 m air temperature"),
            item("prism", "tmean", "PRISM July 2026 mean (800 m)", "PRISM mean air temperature"),
        ),
    ),
    group(
        "Elevation",
        group(
            "Bare-earth elevation",
            item("ct-lidar", "elevation", "CT lidar 2016, 2023 (0.6 m)", "Connecticut lidar elevation (bare earth)"),
            item("3dep", "elevation", "USGS 3DEP (~1 m)", "USGS 3DEP elevation"),
            item("aster-dem", "elevation", "ASTER GDEM v3 (30 m)", "ASTER GDEM v3 elevation"),
        ),
        group(
            "Hillshade",
            item("ct-lidar", "hillshade", "CT lidar 2016, 2023 (0.6 m)", "Connecticut lidar hillshade (bare earth)"),
            item("3dep", "hillshade", "USGS 3DEP (~1 m)", "USGS 3DEP hillshade"),
            item("aster-dem", "hillshade", "ASTER GDEM v3 (30 m)", "ASTER GDEM v3 hillshade"),
        ),
        item("ct-lidar", "surface", "Surface elevation: CT lidar 2023 (0.9 m)", "Connecticut 2023 lidar surface elevation"),
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
        "Radar: NISAR L-band SAR (slow: ~5-10 s per tile)",
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
        group(
            "SMAP root-zone soil moisture (9 km)",
            item("smap", "sm_rootzone", "3-hourly", "SMAP L4 root-zone soil moisture (0-100 cm)"),
            item("smap-prebuilt", "sm_rootzone", "2026-07-30 (pre-built)", "SMAP L4 root-zone soil moisture (0-100 cm)"),
        ),
        group(
            "CHIRPS precipitation (0.05°)",
            item("chirps", "precip", "Daily", "CHIRPS v3 daily precipitation"),
            item("chirps-prebuilt", "precip", "2026-07-29 (pre-built)", "CHIRPS v3 daily precipitation"),
        ),
    ),
    group(
        "Night lights",
        item("viirs-nightlights", "radiance", "VIIRS Black Marble, annual (500 m)", "VIIRS Black Marble night lights"),
        item("viirs-nightlights-prebuilt", "radiance", "VIIRS Black Marble 2025 (500 m, pre-built)", "VIIRS Black Marble night lights"),
    ),
    group(
        "Street maps",
        item("streetmap", "osm", "OpenStreetMap"),
        item("streetmap", "esri", "Esri World Street Map"),
        item("streetmap", "usgs-topo", "USGS National Map topo"),
    ),
]
# endregion tree


# region examples
# The "Example" timestep of each dataset with a time control: a good recent
# image (cloud free, good quality), picked by hand and shown by default (the
# website's Example button returns to it). Keys as in web.time_spec; t2 (end
# of a window), o (window options) and f (filters) are optional. Update by hand.
EXAMPLES = {
    "ct-ortho": dict(t="2023", note="2023 flight, the latest"),
    "naip": dict(t="2023", note="2023-07-05, the latest NAIP over New Haven"),
    "planet": dict(t="2026-07", note="July 2026, as in the figures"),
    "landsat": dict(t="2025-08-22", note="Landsat 9, 2025-08-22: Tier 1, 0.2% cloud over Greater New Haven"),
    "goes-lst": dict(t="2026-06-03T18:00Z", note="2026-06-03 18:00 UTC: clear, high quality (as the pre-built image)"),
    "era5-land": dict(t="2026-07-20T17:00Z", note="2026-07-20 17:00 UTC: a sunny summer afternoon"),
    "ct-lidar": dict(t="2023", note="2023 flight (QL1)"),
    "nisar-gcov": dict(t="2026-07-17", note="2026-07-17: full frame, dry ground"),
    "smap": dict(t="2026-07-30T15:00Z", note="2026-07-30 15:00 UTC: the day after the 2026-07-29 storm"),
    "chirps": dict(t="2026-07-29", note="2026-07-29: one of the wettest days of 2026 at New Haven"),
    "viirs-nightlights": dict(t="2025", note="2025, the latest annual composite"),
}
# endregion examples


# region load-and-resolve
def load_specs() -> tuple[dict, dict]:
    """Sources {"<dataset>/<name>": source} and products {"<dataset>/<product>": product}.

    Each product gets its dataset's `meta` (time, requires, coverage, min_zoom;
    the product's own keys win), and, if it has no coverage, the bounds of its
    COG sources (data stored for the website extent only)."""
    sources, products = {}, {}
    for path in sorted(web.WEB_DATA.glob("*.json")):
        spec = json.loads(path.read_text())
        if "dataset" not in spec:
            continue  # e.g. the ICESat-2 profiles
        ds = spec["dataset"]
        for name, s in spec["sources"].items():
            sources[f"{ds}/{name}"] = s
        for name, p in spec["products"].items():
            p = {"dataset": ds, **spec.get("meta", {}), **p}
            p["layers"] = [{**l, "source": f"{ds}/{l['source']}"} for l in p["layers"]]
            if not p.get("coverage"):
                p["coverage"] = cog_coverage([sources[l["source"]] for l in p["layers"]])
            if p.get("time") and ds in EXAMPLES:
                p["time"] = {**p["time"], "example": example(f"{ds}/{name}", p["time"], EXAMPLES[ds])}
            products[f"{ds}/{name}"] = p
    return sources, products


KEY_FORMS = {"year": r"\d{4}", "month": r"\d{4}-\d\d", "day": r"\d{4}-\d\d-\d\d", "hour": r"\d{4}-\d\d-\d\dT\d\d:00Z", "time": r"\d{4}-\d\d-\d\dT\d\d:\d\dZ"}


def example(pid: str, time: dict, ex: dict) -> dict:
    """An EXAMPLES entry, checked against the product's time spec."""
    for k in ("t", "t2"):
        if k in ex and not re.fullmatch(KEY_FORMS[time["step"]], ex[k]):
            raise ValueError(f"{pid}: example {k}={ex[k]!r} is not a {time['step']} key")
    a = time["availability"]
    if a["type"] == "list" and ex["t"] not in a["values"]:
        raise ValueError(f"{pid}: example {ex['t']} is not one of its timesteps {a['values']}")
    if "t2" in ex and not time.get("window"):
        raise ValueError(f"{pid}: example has an end date but the product has no window")
    return ex


def cog_coverage(layer_sources: list[dict]) -> dict | None:
    """Lon / lat bounds of the COG sources among a product's layers (None if it has none)."""
    from pyproj import Transformer

    cogs = [s for s in layer_sources if s["type"] == "cog"]
    if not cogs:
        return None
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    xmin = min(s["bounds"][0] for s in cogs)
    ymin = min(s["bounds"][1] for s in cogs)
    xmax = max(s["bounds"][2] for s in cogs)
    ymax = max(s["bounds"][3] for s in cogs)
    (w, e), (s_, n) = to_ll.transform([xmin, xmax], [ymin, ymax])
    return web.coverage(round(w, 5), round(s_, 5), round(e, 5), round(n, 5), "Greater New Haven (pre-built for this area only)")


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
