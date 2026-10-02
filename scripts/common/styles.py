"""Color scales shared by several datasets, so that figures of the same
quantity are directly comparable across datasets within a view."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# Elevation (m) color range per view, used by all DEMs (3DEP, CT lidar, ASTER).
ELEVATION_RANGE = {"greater": (0.0, 160.0), "central": (0.0, 50.0)}
# Colorbar "extend" to use with ELEVATION_RANGE.
ELEVATION_EXTEND = "both"
# Land-only part of "terrain" (no blues, so low land does not read as water).
# Values below the range (hydro-flattened water surfaces, ~0 m or below) are
# shown in light blue.
ELEVATION_CMAP = LinearSegmentedColormap.from_list("terrain_land", plt.get_cmap("terrain")(np.linspace(0.25, 1.0, 256)))
ELEVATION_CMAP.set_under("#9ecae1")
