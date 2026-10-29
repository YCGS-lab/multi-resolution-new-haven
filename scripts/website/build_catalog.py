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
from common import config, web
from common.views import CRS


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
        "Street maps",
        item("streetmap", "osm", "OpenStreetMap"),
        item("streetmap", "esri", "Esri World Street Map"),
        item("streetmap", "usgs-topo", "USGS National Map topo"),
    ),
    group(
        "Optical imagery",
        group(
            "True color",
            item("naip", "truecolor", "NAIP (0.3-1 m)", "NAIP, true color"),
            item("planet", "truecolor", "Planet monthly basemap (4.8 m)", "Planet monthly basemap, true color"),
            item("landsat", "truecolor", "Landsat 8-9 (30 m)", "Landsat 8-9 true color"),
        ),
        group(
            "Color infrared",
            item("naip", "cir", "NAIP (0.3-1 m)", "NAIP, color infrared"),
            item("landsat", "cir", "Landsat 8-9 (30 m)", "Landsat 8-9 color infrared"),
        ),
        group(
            "Landsat 8-9",
            item("landsat", "veg", "False color: vegetation", "Landsat 8-9 false color (vegetation)"),
            item("landsat", "urban", "False color: urban", "Landsat 8-9 false color (urban)"),
        ),
    ),
    group(
        "Temperature",
        group(
            "Land surface temperature",
            item("landsat", "lst", "Landsat 8-9 (100 m)", "Landsat 8-9 land surface temperature"),
            item("viirs-lst", "lst", "VIIRS, daily (1 km)", "VIIRS land surface temperature (daily, 1 km)"),
            item("goes-lst", "lst", "GOES-19 ABI, hourly (2 km)", "GOES-19 ABI land surface temperature (2 km)"),
        ),
        item("era5-land", "t2m", "Air temperature: ERA5-Land 2 m, hourly (0.1°)", "ERA5-Land 2 m air temperature"),
    ),
    group(
        "Elevation",
        item("3dep", "elevation", "Bare-earth elevation: USGS 3DEP (~1 m)", "USGS 3DEP elevation"),
        item("3dep", "hillshade", "Hillshade: USGS 3DEP (~1 m)", "USGS 3DEP hillshade"),
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
        item("smap", "sm_rootzone", "SMAP root-zone soil moisture, 3-hourly (9 km)", "SMAP L4 root-zone soil moisture (0-100 cm)"),
        item("chirps", "precip", "CHIRPS precipitation, daily (0.05°)", "CHIRPS v3 daily precipitation"),
    ),
    group(
        "Night lights",
        item("viirs-nightlights", "radiance", "VIIRS Black Marble, annual (500 m)", "VIIRS Black Marble night lights"),
    ),
    # Datasets for one area only: statewide services, and images pre-built for Greater New Haven.
    group(
        "Location-specific",
        group(
            "Connecticut",
            group(
                "Orthoimagery",
                item("ct-ortho", "truecolor", "True color, 1934-2023 (7.6 cm-1 m)", "Connecticut orthoimagery, true color"),
                item("ct-ortho", "cir", "Color infrared, 2012-2023 (7.6-30 cm)", "Connecticut orthoimagery, color infrared"),
            ),
            group(
                "Lidar",
                item("ct-lidar", "elevation", "Bare-earth elevation, 2016, 2023 (0.6 m)", "Connecticut lidar elevation (bare earth)"),
                item("ct-lidar", "hillshade", "Hillshade, 2016, 2023 (0.6 m)", "Connecticut lidar hillshade (bare earth)"),
                item("ct-lidar", "surface", "Surface elevation, 2023 (0.9 m)", "Connecticut 2023 lidar surface elevation"),
            ),
            group(
                "Impervious surface 2023 (pre-built, Greater New Haven)",
                item("ct-impervious-2023", "classes", "Classes", "Connecticut 2023 impervious surface classes"),
                item("ct-impervious-2023", "impervious", "Impervious / not", "Connecticut 2023 impervious surface"),
            ),
            group(
                "Greater New Haven (pre-built)",
                item("landsat-pan", "pan", "Landsat 8 panchromatic, 2024-08-27 (15 m, pre-built, Greater New Haven)", "Landsat 8 panchromatic (OLI band 8)"),
                item("viirs-lst-prebuilt", "lst", "VIIRS LST, 2026-06-03 (750 m swath, pre-built, Greater New Haven)", "VIIRS land surface temperature (750 m)"),
                item("goes-lst-prebuilt", "lst", "GOES-19 ABI LST, 2026-06-03 (2 km, pre-built, Greater New Haven)", "GOES-19 ABI land surface temperature (2 km)"),
                item("prism", "tmean", "PRISM air temperature, July 2026 mean (800 m, pre-built, Greater New Haven)", "PRISM mean air temperature"),
                item("aster-dem", "elevation", "ASTER GDEM v3 elevation (30 m, pre-built, Greater New Haven)", "ASTER GDEM v3 elevation"),
                item("aster-dem", "hillshade", "ASTER GDEM v3 hillshade (30 m, pre-built, Greater New Haven)", "ASTER GDEM v3 hillshade"),
                item("icesat2", "canopy_height", "ICESat-2 canopy height, May-Sep 2025-2026 (pre-built, Greater New Haven)", "ICESat-2 ATL08 canopy height"),
                item("icesat2", "canopy_height_allyears", "ICESat-2 canopy height, growing seasons 2019-2026 (pre-built, Greater New Haven)", "ICESat-2 ATL08 canopy height"),
                item("icesat2", "tracks", "ICESat-2 photon profile sample lines (pre-built, Greater New Haven)", "ICESat-2 photon profile sample lines"),
                item("smap-prebuilt", "sm_rootzone", "SMAP root-zone soil moisture, 2026-07-30 (9 km, pre-built, Greater New Haven)", "SMAP L4 root-zone soil moisture (0-100 cm)"),
                item("chirps-prebuilt", "precip", "CHIRPS precipitation, 2026-07-29 (0.05°, pre-built, Greater New Haven)", "CHIRPS v3 daily precipitation"),
                item("viirs-nightlights-prebuilt", "radiance", "VIIRS Black Marble 2025 (500 m, pre-built, Greater New Haven)", "VIIRS Black Marble night lights"),
            ),
        ),
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
    "viirs-lst": dict(t="2026-06-03", note="2026-06-03: clear, near nadir (the pre-built swath's day)"),
    "goes-lst": dict(t="2026-06-03T18:00Z", note="2026-06-03 18:00 UTC: clear, high quality (as the pre-built image)"),
    "era5-land": dict(t="2026-07-20T17:00Z", note="2026-07-20 17:00 UTC: a sunny summer afternoon"),
    "ct-lidar": dict(t="2023", note="2023 flight (QL1)"),
    "nisar-gcov": dict(t="2026-07-17", note="2026-07-17: full frame, dry ground"),
    "smap": dict(t="2026-07-30T15:00Z", note="2026-07-30 15:00 UTC: the day after the 2026-07-29 storm"),
    "chirps": dict(t="2026-07-29", note="2026-07-29: one of the wettest days of 2026 at New Haven"),
    "viirs-nightlights": dict(t="2025", note="2025, the latest annual composite"),
}
# endregion examples


# region links
# "More info" (the dataset's or mission's home page) and "Data access" (where
# the product shown can be downloaded; not necessarily where the website reads
# it from) on each product's source line. Keys are datasets, or
# "<dataset>/<product>" for one product; a pre-built variant ("<dataset>-prebuilt")
# shares its live dataset's links. Update by hand.
EARTHDATA_SEARCH = "https://search.earthdata.nasa.gov/search/granules?p={}&sb[0]=-73.05%2C41.25%2C-72.79%2C41.36"
LINKS = {
    # USGS EarthExplorer has no stable link to one dataset: pick Landsat > Landsat Collection 2 Level-2 (Level-1 for pan)
    "landsat": dict(info="https://www.usgs.gov/landsat-missions", data="https://earthexplorer.usgs.gov/"),
    "landsat-pan": dict(info="https://www.usgs.gov/landsat-missions/landsat-8", data="https://earthexplorer.usgs.gov/"),
    "naip": dict(
        info="https://www.usgs.gov/centers/eros/science/usgs-eros-archive-aerial-photography-national-agriculture-imagery-program-naip",
        data="https://earthexplorer.usgs.gov/",
    ),
    "planet": dict(info="https://www.planet.com/products/mosaics/", data="https://insights.planet.com/data/mosaics/"),
    "ct-ortho": dict(info="https://maps.cteco.uconn.edu/data/imagery/", data="https://maps.cteco.uconn.edu/download/"),
    "ct-lidar": dict(info="https://maps.cteco.uconn.edu/data/lidar/", data="https://maps.cteco.uconn.edu/download/"),
    "3dep": dict(info="https://www.usgs.gov/3d-elevation-program", data="https://apps.nationalmap.gov/downloader/"),
    # Earthdata Search: the collection, with Greater New Haven drawn as the search box
    "aster-dem": dict(info="https://www.earthdata.nasa.gov/data/catalog/lpcloud-astgtm-003", data=EARTHDATA_SEARCH.format("C1711961296-LPCLOUD")),
    "viirs-lst": dict(info="https://www.earthdata.nasa.gov/data/catalog/lpcloud-vnp21a1d-002", data=EARTHDATA_SEARCH.format("C2545314555-LPCLOUD")),
    # the pre-built image is the VNP21 swath, not the daily grid
    "viirs-lst-prebuilt": dict(info="https://www.earthdata.nasa.gov/data/catalog/lpcloud-vnp21-002", data=EARTHDATA_SEARCH.format("C2545314550-LPCLOUD")),
    "goes-lst": dict(info="https://www.star.nesdis.noaa.gov/goesr/product_land_lst.php", data="https://noaa-goes19.s3.amazonaws.com/index.html#ABI-L2-LSTC/"),
    "era5-land": dict(info="https://www.ecmwf.int/en/era5-land", data="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=download"),
    "prism": dict(info="https://prism.oregonstate.edu/", data="https://data.prism.oregonstate.edu/time_series/us/an/800m/tmean/monthly/2026/"),
    "icesat2": dict(info="https://icesat-2.gsfc.nasa.gov/", data="https://nsidc.org/data/atl08/versions/7"),
    "ct-impervious-2023": dict(
        info="https://maps.cteco.uconn.edu/data/flight2023/impervious/",
        data="https://geodata.ct.gov/datasets/ctmaps::impervious-surface-land-connecticut-2023",
    ),
    "nisar-gcov": dict(info="https://science.nasa.gov/mission/nisar/", data=EARTHDATA_SEARCH.format("C2854338529-ASF")),
    "smap": dict(info="https://smap.jpl.nasa.gov/", data="https://nsidc.org/data/spl4smgp/versions/8"),
    "chirps": dict(info="https://www.chc.ucsb.edu/data/chirps3", data="https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/sat/"),
    "viirs-nightlights": dict(
        info="https://www.earthdata.nasa.gov/data/projects/black-marble",
        data="https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/",
    ),
    "streetmap/osm": dict(info="https://www.openstreetmap.org/about", data="https://planet.openstreetmap.org/"),
    # Esri's data can't be downloaded: both links are the map's item page
    "streetmap/esri": dict(
        info="https://www.arcgis.com/home/item.html?id=3b93337983e9436f8db950e38a8629af",
        data="https://www.arcgis.com/home/item.html?id=3b93337983e9436f8db950e38a8629af",
    ),
    "streetmap/usgs-topo": dict(info="https://www.usgs.gov/programs/national-geospatial-program/national-map", data="https://apps.nationalmap.gov/downloader/"),
}
# endregion links


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
            if links := links_for(ds, name):
                p["links"] = links
            products[f"{ds}/{name}"] = p
    return sources, products


def links_for(dataset: str, product: str) -> dict | None:
    """A product's LINKS entry: its own, its dataset's, or its live dataset's (pre-built variants)."""
    for k in (f"{dataset}/{product}", dataset, dataset.removesuffix("-prebuilt")):
        if k in LINKS:
            return LINKS[k]
    return None


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
    no_links = sorted(pid for pid in products if not links_for(*pid.split("/", 1)))
    if no_links:
        print(f"  no LINKS entry: {', '.join(no_links)}")
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
