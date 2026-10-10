"""The two map windows shared by every figure.

Each view is a fixed rectangle in Web Mercator (EPSG:3857) with a fixed
output size in pixels, so all figures of a given view are pixel-aligned and
directly comparable. Views are defined from Google Maps-style
"@lat,lon,<height>m" windows, where <height> is the ground distance spanned
from the top to the bottom of the image; width follows from the 16:9 aspect.
"""

import json
import math
from dataclasses import dataclass

from pyproj import Transformer
from rasterio.transform import Affine, from_bounds
from rasterio.warp import transform_bounds

from . import config

CRS = "EPSG:3857"
WIDTH_PX, HEIGHT_PX = 3840, 2160  # 16:9

_to_merc = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)


# region view-class
@dataclass(frozen=True)
class View:
    name: str
    title: str
    lat: float
    lon: float
    height_m: float  # ground distance, top to bottom
    width_px: int = WIDTH_PX
    height_px: int = HEIGHT_PX

    @property
    def merc_scale(self) -> float:
        """Web Mercator meters per ground meter at the view center."""
        return 1.0 / math.cos(math.radians(self.lat))

    @property
    def width_m(self) -> float:
        return self.height_m * self.width_px / self.height_px

    @property
    def pixel_size_m(self) -> float:
        """Ground size of one output pixel, in meters."""
        return self.height_m / self.height_px

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) in EPSG:3857."""
        x, y = _to_merc.transform(self.lon, self.lat)
        hw = self.width_m / 2 * self.merc_scale
        hh = self.height_m / 2 * self.merc_scale
        return (x - hw, y - hh, x + hw, y + hh)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """(xmin, xmax, ymin, ymax) for matplotlib's imshow/set_xlim."""
        xmin, ymin, xmax, ymax = self.bounds
        return (xmin, xmax, ymin, ymax)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height_px, self.width_px)

    @property
    def transform(self) -> Affine:
        return from_bounds(*self.bounds, self.width_px, self.height_px)

    def bounds_in(self, crs, pad_m: float = 0.0) -> tuple[float, float, float, float]:
        """View bounds (optionally padded by `pad_m` ground meters) in another CRS.

        Use this to subset data: pad by at least one native pixel so that every
        pixel intersecting the view (including partial edge pixels) is kept.
        """
        xmin, ymin, xmax, ymax = self.bounds
        p = pad_m * self.merc_scale
        return transform_bounds(CRS, crs, xmin - p, ymin - p, xmax + p, ymax + p, densify_pts=51)

    def bounds_lonlat(self, pad_m: float = 0.0) -> tuple[float, float, float, float]:
        """(west, south, east, north) in degrees."""
        return self.bounds_in("EPSG:4326", pad_m)

    def to_xy(self, lon, lat):
        """Lon/lat (scalars or arrays) to EPSG:3857 x, y."""
        return _to_merc.transform(lon, lat)
# endregion view-class


# region views
VIEWS = {
    "greater": View("greater", "Greater New Haven", 41.3038978, -72.9193273, 12092),
    "central": View("central", "Central New Haven and Yale", 41.3136326, -72.9238051, 2158),
}
# endregion views


def all_bounds_lonlat(pad_m: float = 0.0) -> tuple[float, float, float, float]:
    """Lon/lat bounds covering every view (for one download serving all views)."""
    bs = [v.bounds_lonlat(pad_m) for v in VIEWS.values()]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def all_bounds_in(crs, pad_m: float = 0.0) -> tuple[float, float, float, float]:
    """Bounds in `crs` covering every view."""
    bs = [v.bounds_in(crs, pad_m) for v in VIEWS.values()]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def load_landmarks() -> list[dict]:
    """[{name, lat, lon, ...}] from data/landmarks.json."""
    return json.loads((config.DATA / "landmarks.json").read_text())
