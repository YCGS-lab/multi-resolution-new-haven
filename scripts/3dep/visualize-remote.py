# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""USGS 3DEP seamless DEM (best available, ~1 m lidar-derived here), fetched
as raw elevation values from the 3DEP ArcGIS ImageServer.

Figures (per view): elevation (tinted + hillshade) and hillshade (grayscale).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from matplotlib.colors import Normalize

from common import remote, render, styles
from common.views import VIEWS

DATASET = "3dep"
SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
SOURCE = "USGS 3D Elevation Program (3DEP) dynamic DEM, elevation.nationalmap.gov"


def main():
    for view in VIEWS.values():
        print(view.title)
        dem = remote.arcgis_export_image(
            SERVICE,
            view,
            fmt="tiff",
            pixel_type="F32",
            rendering_rule={"rasterFunction": "None"},
            nodata=-9999,
        )[0]
        dem = np.where(dem <= -9999, np.nan, dem)
        print(f"  elevation range {np.nanmin(dem):.1f} to {np.nanmax(dem):.1f} m")
        hs = render.hillshade(dem, view.pixel_size_m)
        vmin, vmax = styles.ELEVATION_RANGE[view.name]
        norm = Normalize(vmin, vmax)
        subtitle = "~1 m lidar-derived (best available); shown at {:.1f} m/pixel".format(view.pixel_size_m)

        img = render.blend_hillshade(render.colorize(dem, styles.ELEVATION_CMAP, norm=norm), hs, 0.5)
        render.save_figures(
            img, view, DATASET, "elevation",
            title="USGS 3DEP elevation",
            subtitle=subtitle,
            colorbar=dict(cmap=styles.ELEVATION_CMAP, norm=norm, label="Elevation (m)", extend=styles.ELEVATION_EXTEND),
            source=SOURCE,
        )  # fmt: skip
        gray = render.colorize(np.where(np.isfinite(dem), hs, np.nan), "gray", 0, 1)
        render.save_figures(
            gray, view, DATASET, "hillshade",
            title="USGS 3DEP hillshade",
            subtitle=subtitle,
            source=SOURCE,
            landmark_color="yellow",
        )  # fmt: skip


if __name__ == "__main__":
    main()
