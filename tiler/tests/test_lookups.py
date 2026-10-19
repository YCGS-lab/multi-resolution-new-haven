import time

import pytest
import shapely.geometry
from geojson_pydantic.geometries import Polygon
from morecantile import Tile
from rio_tiler.constants import WEB_MERCATOR_TMS
from titiler.cmr.models import Granule, GranuleSearch

from ycgs_titiler import granules, lookups, prune, timeres


@pytest.fixture
def store():
    s = lookups.MemoryStore()
    lookups.set_store(s)
    yield s
    lookups.reset()


def granule(gid: str, west: float, south: float, east: float, north: float) -> Granule:
    rect = {
        "WestBoundingCoordinate": west,
        "EastBoundingCoordinate": east,
        "SouthBoundingCoordinate": south,
        "NorthBoundingCoordinate": north,
    }
    return Granule.model_validate(
        {
            "meta": {"concept-id": gid, "native-id": f"ur-{gid}", "collection-concept-id": "C1-TEST"},
            "umm": {"SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"BoundingRectangles": [rect]}}}},
        }
    )


def tile_shape(z: int, x: int, y: int):
    return shapely.geometry.box(*WEB_MERCATOR_TMS.bounds(Tile(x, y, z)))


# region cached
def test_cached_computes_once_and_expires(store):
    calls = []
    compute = lambda: calls.append(1) or {"a": [1, 2]}
    assert lookups.cached("k", {"q": 1}, 60, compute) == {"a": [1, 2]}
    assert lookups.cached("k", {"q": 1}, 60, compute) == {"a": [1, 2]}
    assert len(calls) == 1
    # another query is another entry
    lookups.cached("k", {"q": 2}, 60, compute)
    assert len(calls) == 2
    # an expired entry is recomputed
    (item,) = [i for i in store.items.values() if i["query"] == '{"q":1}']
    item["expires"] = time.time() - 1
    lookups.cached("k", {"q": 1}, 60, compute)
    assert len(calls) == 3


def test_cached_without_store_always_computes():
    lookups.set_store(None)
    calls = []
    for _ in range(2):
        lookups.cached("k", {}, 60, lambda: calls.append(1) or 1)
    assert len(calls) == 2
    lookups.reset()


def test_cached_fails_open(store, monkeypatch):
    def broken(pk):
        raise ConnectionError("dynamodb down")

    monkeypatch.setattr(store, "get", broken)
    monkeypatch.setattr(store, "put", lambda item: broken(None))
    assert lookups.cached("k", {}, 60, lambda: 42) == 42


def test_none_is_not_stored(store):
    assert lookups.cached("k", {}, 60, lambda: None) is None
    assert store.items == {}


def test_ttl_policy():
    now = 1_800_000_000.0
    assert lookups.ttl_for(None, now) == lookups.TTL_SETTLED_S
    assert lookups.ttl_for(now - 30 * 86400, now) == lookups.TTL_SETTLED_S
    assert lookups.ttl_for(now - 3600, now) == lookups.TTL_RECENT_S


# endregion cached


# region granules
def test_parent_tile():
    child = Tile(1210, 1534, 12)
    assert granules.parent_tile(WEB_MERCATOR_TMS.bounds(child)) == Tile(75, 95, 8)
    # a z8 tile is its own parent; a box across a z8 tile edge has a lower-zoom parent
    assert granules.parent_tile(WEB_MERCATOR_TMS.bounds(Tile(75, 95, 8))) == Tile(75, 95, 8)
    _, south, east, _ = WEB_MERCATOR_TMS.bounds(Tile(75, 95, 8))
    t = granules.parent_tile((east - 0.1, south, east + 0.1, south + 0.1))
    assert t.z < 8
    assert granules.parent_tile((-180, -90, 180, 90)) == Tile(0, 0, 0)


def test_select_like_get_granules():
    shape = shapely.geometry.box(-73.0, 41.0, -72.9, 41.1)
    gs = [
        granule("far", 10, 10, 11, 11),  # doesn't intersect
        granule("half", -73.2, 40.9, -72.95, 41.2),  # covers the west half
        granule("dup", -73.2, 40.9, -72.95, 41.2),  # same footprint
        granule("rest", -73.0, 40.9, -72.8, 41.2),  # covers the rest
        granule("extra", -74, 40, -72, 42),  # after full coverage
    ]
    sel, ended = granules.select(gs, shape, 0.0, 100, skipcovered=False)
    assert [g.id for g in sel] == ["half", "dup", "rest"] and ended
    sel, _ = granules.select(gs, shape, 0.0, 100, skipcovered=True)
    assert [g.id for g in sel] == ["half", "rest"]
    sel, ended = granules.select(gs, shape, 0.0, 1, skipcovered=False)
    assert [g.id for g in sel] == ["half"] and ended
    sel, ended = granules.select(gs[:2], shape, 0.0, 100, skipcovered=False)
    assert [g.id for g in sel] == ["half"] and not ended


def test_cached_backend_searches_once_per_parent_tile(store, monkeypatch):
    searches = []
    footprint = granule("g1", -74.0, 40.5, -72.0, 42.5)

    def fake_get_granules(search_params, client, geometry=None, **kw):
        searches.append(shapely.geometry.shape(geometry.model_dump()).bounds)
        yield footprint

    monkeypatch.setattr(granules, "get_granules", fake_get_granules)
    backend = granules.CachedCMRBackend(
        GranuleSearch(collection_concept_id="C1-TEST", temporal="2024-08-27T00:00:01Z/2024-08-27T23:59:59Z"),
        client=None,
        reader=None,
    )
    for x, y in [(1210, 1534), (1211, 1534), (1210, 1535)]:
        geom = Polygon.from_bounds(*WEB_MERCATOR_TMS.bounds(Tile(x, y, 12)))
        assert [g.id for g in backend.get_assets(geom)] == ["g1"]
    assert len(searches) == 1
    assert searches[0] == pytest.approx(WEB_MERCATOR_TMS.bounds(Tile(75, 95, 8)))


def test_cached_backend_falls_back_when_list_is_truncated(store, monkeypatch):
    calls = []

    def fake_get_granules(search_params, client, geometry=None, limit=100, **kw):
        calls.append(limit)
        yield from [granule(f"g{i}", 10, 10, 11, 11) for i in range(min(limit, granules.SEARCH_LIMIT))]

    monkeypatch.setattr(granules, "get_granules", fake_get_granules)
    monkeypatch.setattr("titiler.cmr.backend.get_granules", fake_get_granules)
    backend = granules.CachedCMRBackend(GranuleSearch(collection_concept_id="C1-TEST"), client=None, reader=None)
    geom = Polygon.from_bounds(*WEB_MERCATOR_TMS.bounds(Tile(1210, 1534, 12)))
    backend.get_assets(geom)
    assert calls == [granules.SEARCH_LIMIT, 100]  # the parent's (truncated), then the request's own


def test_data_end():
    t = granules.data_end(
        GranuleSearch(collection_concept_id="C", temporal="2024-08-27T00:00:01Z/2024-08-27T23:59:59Z")
    )
    assert t == timeres.parse_datetime("2024-08-27T23:59:59Z").timestamp()
    assert granules.data_end(GranuleSearch(collection_concept_id="C")) is None


# endregion granules


# region goes
def test_complete_goes_hours_are_listed_once_across_environments(store, monkeypatch):
    listed = []
    monkeypatch.setattr(timeres, "_list", lambda b, p: listed.append(p) or ("a", "b"))
    timeres.clear_caches()
    assert timeres._list_complete_hour("noaa-goes19", "ABI-L2-LSTC/2026/154/18/") == ("a", "b")
    timeres.clear_caches()  # a new execution environment
    assert timeres._list_complete_hour("noaa-goes19", "ABI-L2-LSTC/2026/154/18/") == ("a", "b")
    assert listed == ["ABI-L2-LSTC/2026/154/18/"]
    timeres.clear_caches()


# endregion goes


# region prune
def test_prune(store, monkeypatch):
    now = time.time()
    results = {"same": 1, "changed": 1, "fails": 1}
    lookups.register("test", lambda q: results[q["id"]])

    def boom(q):
        raise TimeoutError

    lookups.register("test-error", boom)
    for qid in results:
        lookups.put(store, "test", {"id": qid}, 1, lookups.TTL_SETTLED_S, now)
    lookups.put(store, "test-error", {"id": "x"}, 1, lookups.TTL_SETTLED_S, now)
    lookups.put(store, "test", {"id": "recent"}, 1, lookups.TTL_RECENT_S, now)
    lookups.put(store, "test", {"id": "old"}, 1, 60, now - 120)
    lookups.put(store, "gone", {"id": "y"}, 1, lookups.TTL_SETTLED_S, now)
    results["changed"] = 2
    counts = prune.prune(store, now)
    assert counts == {"valid": 2, "changed": 1, "error": 1, "recent": 1, "expired": 1, "unknown_kind": 1}
    remaining = sorted(i["query"] for i in store.items.values())
    assert remaining == ['{"id":"fails"}', '{"id":"recent"}', '{"id":"same"}', '{"id":"x"}']
    # past the deadline, settled entries are left for next week
    assert prune.prune(store, now, deadline=0.0) == {"deferred": 3, "recent": 1}
    del lookups.KINDS["test"], lookups.KINDS["test-error"]


# endregion prune
