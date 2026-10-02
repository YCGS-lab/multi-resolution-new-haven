# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ASTER Global DEM v3 (ASTGTM.003, 1 arc-second, ~30 m) for the views.

Mosaics the downloaded 1x1 degree tiles (run download.py first), subsets them
to the padded view bounds and writes, per view: elevation (tinted + hillshade)
and hillshade (grayscale). The hillshade is computed on the native 1" grid and
then resampled with nearest neighbor, so each ~30 m pixel shows up as a block.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from matplotlib.colors import Normalize
from rasterio.merge import merge

from common import config, render, styles, views
from common.views import VIEWS

DATASET = "aster-dem"
PAD_M = 100.0  # > 3 native pixels
SOURCE = "ASTER GDEM v3 (ASTGTM.003), NASA/METI, via NASA LP DAAC / Earthdata"
SUBTITLE = "1 arc-second (~30 m) global DEM from ASTER stereo, 2000-2013; shown at {:.1f} m/pixel"


def load_mosaic():
    """Mosaic of the tiles, subset to every view (padded). Returns (dem, transform, crs)."""
    files = sorted(config.data_dir(DATASET).glob("ASTGTMV003_*_dem.tif"))
    if not files:
        raise SystemExit("no ASTER tiles in data/aster-dem; run download.py first")
    srcs = [rasterio.open(f) for f in files]
    try:
        crs = srcs[0].crs
        dem, transform = merge(srcs, bounds=views.all_bounds_in(crs, PAD_M), nodata=-9999)
    finally:
        for s in srcs:
            s.close()
    dem = dem[0].astype("float32")
    dem[dem <= -9999] = np.nan
    return dem, transform, crs


def main():
    dem, transform, crs = load_mosaic()
    print(f"native mosaic {dem.shape}, elevation {np.nanmin(dem):.0f} to {np.nanmax(dem):.0f} m")

    # Hillshade on the native geographic grid, with ground pixel spacing in m.
    lat = transform.f + transform.e * dem.shape[0] / 2
    dx = abs(transform.a) * 111320 * math.cos(math.radians(lat))
    dy = abs(transform.e) * 110574
    hs = np.where(np.isfinite(dem), render.hillshade(dem, dx, dy), np.nan)

    for view in VIEWS.values():
        print(view.title)
        grid = render.reproject_to_view(dem, transform, crs, view, resampling="nearest")
        hs_grid = render.reproject_to_view(hs, transform, crs, view, resampling="nearest")
        vmin, vmax = styles.ELEVATION_RANGE[view.name]
        norm = Normalize(vmin, vmax)
        subtitle = SUBTITLE.format(view.pixel_size_m)

        img = render.blend_hillshade(render.colorize(grid, styles.ELEVATION_CMAP, norm=norm), hs_grid, 0.5)
        render.save_figures(
            img, view, DATASET, "elevation",
            title="ASTER GDEM v3 elevation",
            subtitle=subtitle,
            colorbar=dict(cmap=styles.ELEVATION_CMAP, norm=norm, label="Elevation (m)", extend=styles.ELEVATION_EXTEND),
            source=SOURCE,
        )  # fmt: skip
        gray = render.colorize(hs_grid, "gray", 0, 1)
        render.save_figures(
            gray, view, DATASET, "hillshade",
            title="ASTER GDEM v3 hillshade",
            subtitle=subtitle,
            source=SOURCE,
            landmark_color="yellow",
        )  # fmt: skip


if __name__ == "__main__":
    main()
