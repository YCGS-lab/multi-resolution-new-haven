"""CMR granule searches through the lookup cache (titiler-cmr's mosaic backend).

titiler-cmr searches CMR once per tile, point or bbox request, for the
granules intersecting that request. CMR's latency varies from ~0.15 s to
over 20 s for the same query, so a viewport of tiles can wait seconds on
search alone. `CachedCMRBackend` instead searches once per *parent tile*
(the Web Mercator tile at `YCGS_GRANULE_CACHE_ZOOM`, default 8, ~120 km at
New Haven, containing the request), stores the result in the lookup cache,
and picks each request's granules from it locally, the way titiler-cmr's
`get_granules` would: in CMR order, granules intersecting the request,
stopping once it is covered.

The parent search stops once the parent tile is covered, so the request's
granules are a prefix of the same ordered list. If the stored list was cut
off at `SEARCH_LIMIT` before the request was covered, the request falls
back to its own CMR search.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

import shapely
import shapely.geometry
from geojson_pydantic.geometries import Geometry, Polygon
from httpx2 import Client
from morecantile import Tile
from rio_tiler.constants import WEB_MERCATOR_TMS
from titiler.cmr.backend import CMRBackend
from titiler.cmr.models import Granule, GranuleSearch
from titiler.cmr.query import CMR_GRANULE_SEARCH_API, get_granules

from . import lookups

CACHE_ZOOM = int(os.environ.get("YCGS_GRANULE_CACHE_ZOOM", "8"))
SEARCH_LIMIT = 200
PAGE_SIZE = 50
# Granules within this distance (degrees, ~100 m) of a request count as
# intersecting it: CMR intersects on the sphere, shapely in lon/lat, and an
# extra granule only costs a read that finds no pixels, a missing one a gap.
INTERSECT_SLACK = 1e-3
# titiler-cmr's get_granules default
DEFAULT_LIMIT = 100
KIND = "cmr-granules"
MAX_LAT = 85.0511287798066


# region parent-tile
def parent_tile(bounds: tuple[float, float, float, float], zoom: int = CACHE_ZOOM) -> Tile:
    """The highest-zoom tile, at most `zoom`, containing lon/lat `bounds`."""
    minx, miny, maxx, maxy = bounds
    eps = 1e-9
    w, e = max(minx, -180.0), min(maxx, 180.0) - eps
    s, n = max(miny, -MAX_LAT) + eps, min(maxy, MAX_LAT)
    for z in range(zoom, 0, -1):
        if (t := WEB_MERCATOR_TMS.tile(w, n, z)) == WEB_MERCATOR_TMS.tile(e, s, z):
            return t
    return Tile(0, 0, 0)


# endregion parent-tile


# region search-parent
def search_parent(query: dict, client: Client | None = None) -> dict:
    """Granules of a search over a parent tile, in CMR order, until the tile is covered."""
    tile = Tile(*query["tile"])
    geometry = Polygon.from_bounds(*WEB_MERCATOR_TMS.bounds(tile))
    search = GranuleSearch.model_validate(query["search"])
    own = client is None
    client = client or Client(base_url=CMR_GRANULE_SEARCH_API, timeout=30)
    try:
        granules = list(
            get_granules(
                search_params=search,
                client=client,
                geometry=geometry,
                page_size=PAGE_SIZE,
                limit=SEARCH_LIMIT,
                exitwhenfull=True,
                coverage_tolerance=query["tolerance"],
            )
        )
    finally:
        if own:
            client.close()
    return {
        "granules": [g.model_dump(mode="json", by_alias=True, exclude={"geometry"}) for g in granules],
        "complete": len(granules) < SEARCH_LIMIT,
    }


lookups.register(KIND, search_parent)


def data_end(search: GranuleSearch) -> float | None:
    """End of the search's time filter (epoch), None if it has none."""
    if not search.temporal:
        return None
    from .timeres import parse_datetime

    parts = [p for p in search.temporal.replace(",", "/").split("/") if p]
    try:
        return parse_datetime(parts[-1]).timestamp()
    except ValueError:
        return dt.datetime.now(dt.UTC).timestamp()


# endregion search-parent


# region select
def select(
    granules: list[Granule], shape: shapely.Geometry, tolerance: float, limit: int, skipcovered: bool
) -> tuple[list[Granule], bool]:
    """The granules titiler-cmr's get_granules would return for `shape`, and
    whether the list ended for a reason of its own (covered or at `limit`)."""
    probe = shape.buffer(INTERSECT_SLACK)
    check = shape.buffer(tolerance) if tolerance else shape
    covered: shapely.Geometry = shapely.GeometryCollection()
    seen: list[shapely.Geometry] = []
    out = []
    for g in granules:
        gs = shapely.geometry.shape(g.geometry) if g.geometry else None
        if gs is not None and not gs.intersects(probe):
            continue
        if skipcovered and gs is not None:
            if any(gs.equals(s) for s in seen):
                continue
            seen.append(gs)
        out.append(g)
        if len(out) >= limit:
            return out, True
        if gs is not None:
            covered = covered.union(gs)
            if check.covered_by(covered):
                return out, True
    return out, False


# endregion select


# region cached-backend
class CachedCMRBackend(CMRBackend):
    """titiler-cmr's CMR mosaic backend, with granule searches per parent tile, cached."""

    def get_assets(
        self,
        geometry: Geometry,
        exitwhenfull: bool = True,
        coverage_tolerance: float = 0.0,
        items_limit: int | None = None,
        skipcovered: bool | None = None,
        **kwargs: Any,
    ) -> list[Granule]:
        def direct() -> list[Granule]:
            return super(CachedCMRBackend, self).get_assets(
                geometry, exitwhenfull, coverage_tolerance, items_limit, skipcovered, **kwargs
            )

        # Without stopping at full coverage a request may need granules past
        # the parent's list.
        if not exitwhenfull or lookups.store() is None:
            return direct()
        shape = shapely.geometry.shape(geometry.model_dump())
        tile = parent_tile(shape.bounds)
        query = {
            "search": self.input.model_dump(mode="json", exclude_none=True),
            "tile": [tile.x, tile.y, tile.z],
            "tolerance": coverage_tolerance,
        }
        ttl = lookups.ttl_for(data_end(self.input))
        result = lookups.cached(KIND, query, ttl, lambda: search_parent(query, self.client))
        granules = [Granule.model_validate(g) for g in result["granules"]]
        selected, ended = select(granules, shape, coverage_tolerance, items_limit or DEFAULT_LIMIT, bool(skipcovered))
        if not ended and not result["complete"]:
            return direct()
        return selected


# endregion cached-backend
