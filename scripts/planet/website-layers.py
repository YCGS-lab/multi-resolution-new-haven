# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for the Planet monthly basemaps (PlanetScope), read live from
Planet's tile service with the API key the user enters on the website
(Credentials; kept in the browser, never in the catalog). The months come
from the Basemaps API: the `global_monthly_YYYY_MM_mosaic` mosaics the key
can read. Without a key the dataset is locked.

The mosaics live on the Web Mercator z15 grid (4.78 m, ~3.6 m on the ground
at New Haven): tiles are requested up to z15 and drawn with nearest neighbor.

Products: truecolor.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import remote, web

DATASET = "planet"
NATIVE_ZOOM = 15
SOURCE = "Planet Labs PBC, PlanetScope monthly basemaps"
TILE_URL = "https://tiles.planet.com/basemaps/v1/planet-tiles/{time:mosaic}/gmap/{z}/{x}/{y}.png?api_key={credential:planet}"


def main():
    # region planet-live-source
    sources = {"rgb": web.xyz_source(TILE_URL, max_zoom=NATIVE_ZOOM, smooth=False)}
    meta = dict(
        time=web.time_spec("month", web.avail_planet(), label="Month"),
        requires=web.requires_credential("planet"),
        min_zoom=9,
    )
    # endregion planet-live-source
    native_merc = remote.tile_pixel_size(NATIVE_ZOOM)
    products = {
        "truecolor": web.product(
            title="Planet monthly basemap, true color",
            subtitle="Monthly mosaic (PlanetScope); basemap RGB shown as is",
            native=f"{native_merc:.2f} m Web Mercator grid (~{native_merc / web.EXTENT_VIEW.merc_scale:.1f} m on the ground at New Haven)",
            source=SOURCE,
            layers=[web.layer("rgb", web.identity())],
        )
    }
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
