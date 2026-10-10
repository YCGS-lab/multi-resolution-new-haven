# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for street maps: XYZ tile basemaps that need no credentials,
read by the website directly (no local copy).

  osm        OpenStreetMap Standard (tile.openstreetmap.org), zoom 0-19
  esri       Esri World Street Map (ArcGIS Online tile service), zoom 0-19
  usgs-topo  USGS The National Map, USGSTopo (public domain), zoom 0-16

(CARTO's basemaps now need an API key; Google Maps tiles need a key and may
not be used outside Google's own APIs.) The Esri and USGS attributions are
read from their services.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import remote, web

DATASET = "streetmap"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer"
USGS = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer"


# region basemap-sources
def copyright_text(service: str) -> str:
    r = remote.session().get(service, params={"f": "json"}, timeout=60)
    r.raise_for_status()
    return r.json()["copyrightText"].strip().removeprefix("Sources: ")  # shown after "Source: "


def main():
    sources = {
        "osm": web.xyz_source(remote.OSM_URL, max_zoom=19, attribution=remote.OSM_ATTRIBUTION),
        "esri": web.xyz_source(f"{ESRI}/tile/{{z}}/{{y}}/{{x}}", max_zoom=19, attribution=copyright_text(ESRI)),
        "usgs-topo": web.xyz_source(f"{USGS}/tile/{{z}}/{{y}}/{{x}}", max_zoom=16, attribution=copyright_text(USGS)),
    }
# endregion basemap-sources
    for name, s in sources.items():
        print(f"  {name}: {s['attribution']}")
    products = {
        "osm": web.product(
            title="OpenStreetMap",
            subtitle="OpenStreetMap Standard map tiles (tile.openstreetmap.org)",
            native="map tiles, zoom levels 0-19",
            layers=[web.layer("osm", web.identity())],
        ),
        "esri": web.product(
            title="Esri World Street Map",
            subtitle="ArcGIS Online World_Street_Map tiles (server.arcgisonline.com)",
            native="map tiles, zoom levels 0-19",
            layers=[web.layer("esri", web.identity())],
        ),
        "usgs-topo": web.product(
            title="USGS National Map topographic base map",
            subtitle="The National Map USGSTopo tiles (basemap.nationalmap.gov), public domain",
            native="map tiles, zoom levels 0-16",
            layers=[web.layer("usgs-topo", web.identity())],
        ),
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
