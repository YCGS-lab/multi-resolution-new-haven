# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Planet monthly basemap (PlanetScope), July 2026, from Planet Basemaps XYZ tiles.

Mosaic `global_monthly_2026_07_mosaic` (product_type "timelapse", built from
PSScene acquired 2026-07-01 to 2026-08-01) lives on the Web Mercator z15 grid:
4.777 m per pixel in EPSG:3857 units, i.e. ~3.6 m on the ground at New Haven.
Tiles are fetched at z15 only (never finer, which would just be upsampled by
Planet) and placed on the view grid by averaging (greater view) or nearest
neighbor (central view, so the native pixels show as blocks).

Figures (per view): truecolor.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests

from common import config, remote, render
from common.views import VIEWS

DATASET = "planet"
MOSAIC = "global_monthly_2026_07_mosaic"
NATIVE_ZOOM = 15
TILE_URL = "https://tiles.planet.com/basemaps/v1/planet-tiles/" + MOSAIC + "/gmap/{z}/{x}/{y}.png?api_key={key}"
SOURCE = f"Planet Labs PBC, PlanetScope monthly basemap {MOSAIC}"


def main():
    key = config.credentials()["planet_api_key"]
    # Fill in the key now, keep the {z}/{x}/{y} placeholders. Never print this.
    url = TILE_URL.replace("{key}", key)
    native_merc = remote.tile_pixel_size(NATIVE_ZOOM)
    for view in VIEWS.values():
        print(view.title)
        native_ground = native_merc / view.merc_scale
        coarse = native_ground > view.pixel_size_m
        try:
            img = remote.fetch_xyz(url, view, zoom=NATIVE_ZOOM, resampling="nearest" if coarse else "average")
        except requests.RequestException as e:  # error messages contain the URL: redact the key
            raise RuntimeError(str(e).replace(key, "<planet_api_key>")) from None
        subtitle = (
            f"July 2026 monthly mosaic (PlanetScope); "
            f"native {native_merc:.2f} m Web Mercator grid (~{native_ground:.1f} m on the ground); "
            f"shown at {view.pixel_size_m:.1f} m/pixel"
        )
        render.save_figures(
            img, view, DATASET, "truecolor",
            title="Planet monthly basemap, true color",
            subtitle=subtitle,
            source=SOURCE,
        )  # fmt: skip


if __name__ == "__main__":
    main()
