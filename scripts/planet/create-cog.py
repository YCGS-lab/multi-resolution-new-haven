# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Planet monthly basemap (July 2026) as a COG for the website: the RGB values
of the z15 XYZ tiles, copied pixel for pixel onto a Web Mercator grid with
the tiles' own pixel size (4.78 m Web Mercator, ~3.6 m on the ground), and
shown as they are.

Stored locally (~20 MB) rather than read by the website from Planet's tile
service, which would put the API key in the browser.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import requests

from common import config, remote, web

_spec = importlib.util.spec_from_file_location("visualize_remote", Path(__file__).parent / "visualize-remote.py")
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

DATASET = vr.DATASET


def main():
    key = config.credentials()["planet_api_key"]
    url = vr.TILE_URL.replace("{key}", key)  # never print this
    native_merc = remote.tile_pixel_size(vr.NATIVE_ZOOM)
    grid = web.Grid(native_merc / web.EXTENT_VIEW.merc_scale)  # aligned with the z15 tile pixels
    try:
        rgba = remote.fetch_xyz(url, grid, zoom=vr.NATIVE_ZOOM, resampling="nearest")  # 1:1 copy
    except requests.RequestException as e:  # error messages contain the URL: redact the key
        raise RuntimeError(str(e).replace(key, "<planet_api_key>")) from None
    print(f"  {(rgba[..., 3] == 0).mean():.2%} of pixels without data")
    sources = {"rgb": web.write_cog(DATASET, np.moveaxis(rgba[..., :3], -1, 0), grid, ["r", "g", "b"], kind="jpeg")}
    products = {
        "truecolor": web.product(
            title="Planet monthly basemap, true color",
            subtitle="July 2026 monthly mosaic (PlanetScope); basemap RGB shown as is",
            native=f"{native_merc:.2f} m Web Mercator grid (~{grid.pixel_m:.1f} m on the ground)",
            source=vr.SOURCE,
            layers=[web.layer("rgb", web.identity())],
        )
    }
    web.write_spec(DATASET, sources, products)


if __name__ == "__main__":
    main()
