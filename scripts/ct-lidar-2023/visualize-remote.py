# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Connecticut 2023 statewide QL1 lidar, fetched as raw values from the CT ECO
(UConn CLEAR / CT DEEP) ArcGIS ImageServers.

  - elevation/Statewide2023: bare-earth DEM, 2 ft pixels, CT State Plane
    NAD83(2011) ftUS (EPSG:6434), elevations in US survey feet (NAVD88).
  - elevation/MaxSurfaceHeight_2023: maximum lidar surface elevation (a DSM:
    buildings, trees; absolute elevation in feet, not height above ground),
    published in Web Mercator with 4 ft (1.22 m) Mercator pixels.

Elevations are converted to meters so the shared styles.ELEVATION_RANGE applies.
Figures (per view): elevation (tinted DEM + hillshade), hillshade (grayscale,
DEM), and surface (tinted DSM + DSM hillshade).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from matplotlib.colors import Normalize

from common import remote, render, styles
from common.views import VIEWS

DATASET = "ct-lidar-2023"
BASE = "https://cteco.uconn.edu/ctraster/rest/services/elevation"
DEM_SERVICE = f"{BASE}/Statewide2023/ImageServer"
DSM_SERVICE = f"{BASE}/MaxSurfaceHeight_2023/ImageServer"
FT_US = 1200 / 3937  # meters per US survey foot
SOURCE = "CT 2023 statewide QL1 lidar (CT GIS Office), CT ECO image services (UConn CLEAR / CT DEEP)"
ACQ = "Lidar flown Mar-Apr 2023 (leaf-off)"


def fetch(service: str, view) -> np.ndarray:
    """Raw elevation (m) on the view grid; NaN outside coverage."""
    z = remote.arcgis_export_image(
        service,
        view,
        fmt="tiff",
        pixel_type="F32",
        rendering_rule={"rasterFunction": "None"},
        nodata=-9999,
    )[0]
    z = np.where((z <= -9999) | ~np.isfinite(z), np.nan, z)
    return z * FT_US


def save_tinted(z, hs, view, product, title, subtitle):
    vmin, vmax = styles.ELEVATION_RANGE[view.name]
    norm = Normalize(vmin, vmax)
    img = render.blend_hillshade(render.colorize(z, styles.ELEVATION_CMAP, norm=norm), hs, 0.5)
    render.save_figures(
        img, view, DATASET, product,
        title=title,
        subtitle=subtitle,
        colorbar=dict(cmap=styles.ELEVATION_CMAP, norm=norm, label="Elevation (m)", extend=styles.ELEVATION_EXTEND),
        source=SOURCE,
    )  # fmt: skip


def main():
    for view in VIEWS.values():
        print(view.title)
        shown = f"shown at {view.pixel_size_m:.1f} m/pixel"

        dem = fetch(DEM_SERVICE, view)
        print(f"  DEM range {np.nanmin(dem):.1f} to {np.nanmax(dem):.1f} m")
        hs = render.hillshade(dem, view.pixel_size_m)
        subtitle = f"{ACQ}; bare-earth DEM, 2 ft (0.61 m) pixels; {shown}"
        save_tinted(dem, hs, view, "elevation", "Connecticut 2023 lidar elevation (bare earth)", subtitle)
        gray = render.colorize(np.where(np.isfinite(dem), hs, np.nan), "gray", 0, 1)
        render.save_figures(
            gray, view, DATASET, "hillshade",
            title="Connecticut 2023 lidar hillshade (bare earth)",
            subtitle=subtitle,
            source=SOURCE,
            landmark_color="yellow",
        )  # fmt: skip

        dsm = fetch(DSM_SERVICE, view)
        print(f"  DSM range {np.nanmin(dsm):.1f} to {np.nanmax(dsm):.1f} m")
        hs_dsm = render.hillshade(dsm, view.pixel_size_m)
        subtitle = f"{ACQ}; maximum surface elevation (buildings, trees), ~0.9 m pixels; {shown}"
        save_tinted(dsm, hs_dsm, view, "surface", "Connecticut 2023 lidar surface elevation", subtitle)


if __name__ == "__main__":
    main()
