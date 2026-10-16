# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for the Connecticut statewide lidar: the website reads raw
elevation tiles (float32, US survey feet, converted to meters) straight from
the CT ECO ImageServers and colors / hillshades them itself, so there is no
local copy:

  - elevation/Statewide2016, Statewide2023: bare-earth DEMs of the 2016 and
    2023 flights (a drop-down of the two years), 2 ft (0.61 m) pixels
  - elevation/MaxSurfaceHeight_2023: maximum lidar surface elevation (DSM:
    buildings, trees), 4 ft Web Mercator pixels (~0.9 m on the ground)

Products: elevation (tinted DEM + hillshade), hillshade (DEM), surface
(tinted DSM + DSM hillshade). Figures of the 2023 flight: scripts/ct-lidar-2023/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.colors import Normalize

from common import styles, web

DATASET = "ct-lidar"
BASE = "https://cteco.uconn.edu/ctraster/rest/services/elevation"
FT_US = 1200 / 3937  # meters per US survey foot
SOURCE = "CT statewide lidar (CT GIS Office / CT DEEP), CT ECO image services (UConn CLEAR / CT DEEP)"
ACQ = "Leaf-off lidar"
FLIGHTS = {"2016": "2016: flown spring 2016 (QL2)", "2023": "2023: flown Mar-Apr 2023 (QL1)"}
# region raw-float-scaled-sources
DSM_NATIVE_M = 1.2192024384048763 / web.EXTENT_VIEW.merc_scale  # 4 ft Web Mercator pixels


def tinted(band: str) -> dict:
    norm = Normalize(*styles.ELEVATION_RANGE["greater"])
    return web.colormap(
        styles.ELEVATION_CMAP,
        norm,
        "Elevation (m)",
        band=band,
        extend=styles.ELEVATION_EXTEND,
        shade=dict(band=band, strength=0.5),
    )


def main():
    sources = {
        "dem": web.arcgis_source(
            f"{BASE}/Statewide2023/ImageServer", 2 * FT_US, bands=["elevation"], raw=True, scale=FT_US, nodata=-9999,
            variants={y: web.arcgis_variant(f"{BASE}/Statewide{y}/ImageServer", 2 * FT_US) for y in FLIGHTS},
        ),
        "dsm": web.arcgis_source(
            f"{BASE}/MaxSurfaceHeight_2023/ImageServer", DSM_NATIVE_M, bands=["surface"], raw=True, scale=FT_US, nodata=-9999
        ),
    }
# endregion raw-float-scaled-sources
    products = {
        "elevation": web.product(
            title="Connecticut lidar elevation (bare earth)",
            subtitle=f"{ACQ}; bare-earth DEM",
            native="2 ft (0.61 m)",
            source=SOURCE,
            layers=[web.layer("dem", tinted("elevation"))],
        ),
        "hillshade": web.product(
            title="Connecticut lidar hillshade (bare earth)",
            subtitle=f"{ACQ}; bare-earth DEM",
            native="2 ft (0.61 m)",
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("dem", web.colormap("gray", Normalize(0, 1), band="elevation", hillshade=True))],
        ),
        "surface": web.product(
            title="Connecticut 2023 lidar surface elevation",
            subtitle="Lidar flown Mar-Apr 2023 (leaf-off); maximum surface elevation (buildings, trees)",
            time=web.time_spec("year", web.avail_list(["2023"], labels={"2023": FLIGHTS["2023"]}), label="Flight", widget="list"),
            native=f"4 ft Web Mercator pixels (~{DSM_NATIVE_M:.1f} m)",
            source=SOURCE,
            layers=[web.layer("dsm", tinted("surface"))],
        ),
    }
    meta = dict(
        time=web.time_spec("year", web.avail_list(list(FLIGHTS), labels=FLIGHTS), label="Flight", widget="list"),
        coverage=web.CONNECTICUT,
        min_zoom=12,
    )
    web.write_spec(DATASET, sources, products, meta)


if __name__ == "__main__":
    main()
