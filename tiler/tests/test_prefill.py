import argparse
import datetime as dt

import pytest
from conftest import utc
from fastapi.testclient import TestClient
from rio_tiler.constants import WEB_MERCATOR_TMS

from ycgs_titiler import granules, lookups, prefill, presets, timeres
from ycgs_titiler.presets import CMR_BACKENDS, GranuleTime


@pytest.fixture
def store():
    s = lookups.MemoryStore()
    lookups.set_store(s)
    yield s
    lookups.reset()


def test_datetimes_cover_api_and_website_forms():
    day = GranuleTime(kind="granule", align="day")
    assert prefill.datetimes(day, utc(2024, 8, 27, 15, 47, 12)) == [
        "2024-08-27T00:00:00Z",
        "2024-08-27T00:00:00Z/2024-08-27T23:59:59Z",
    ]
    instant = GranuleTime(kind="granule", align="instant")
    assert prefill.datetimes(instant, utc(2026, 7, 30, 15)) == [
        "2026-07-30T15:00:00Z",
        "2026-07-30T15:00:00Z/2026-07-30T15:00:59Z",
    ]


def test_parent_tiles_below_cache_zoom_are_their_own_parents():
    ds = presets.catalog().datasets["smap-l4"]
    aoi = presets.catalog().aoi
    assert prefill.parent_tiles(ds, aoi, [8]) == [[76, 95, 8]]
    assert prefill.parent_tiles(ds, aoi, [0, 1]) == [[0, 0, 0], [0, 0, 1]]


@pytest.fixture
def cmr_client(monkeypatch, store):
    """The app with titiler-cmr mounted; CMR searches recorded and answered with no granules."""
    from ycgs_titiler.main import create_app
    from ycgs_titiler.settings import settings

    monkeypatch.setenv("TITILER_CMR_EARTHDATA_USERNAME", "user")
    monkeypatch.setenv("TITILER_CMR_EARTHDATA_PASSWORD", "password")
    monkeypatch.setattr(settings, "features", "cmr")
    monkeypatch.setattr(settings, "origin_verify", None)
    monkeypatch.setattr(granules, "get_granules", lambda *a, **kw: iter(()))
    presets.catalog.cache_clear()
    app = create_app()
    from titiler.cmr import main as cmr

    monkeypatch.setattr(cmr.app.state, "earthdata_token_provider", lambda: "token")
    yield TestClient(app, raise_server_exceptions=False)
    presets.catalog.cache_clear()


def website_datetime(spec: GranuleTime, t: dt.datetime) -> str:
    """`datetime` as website/js/tiles.js sends it for an "interval" source."""
    step = {"instant": dt.timedelta(minutes=1)}.get(spec.align)
    start, end = (t, t + step) if step else timeres.step_range(t, spec.align)
    return f"{timeres.iso(start)}/{timeres.iso(end - dt.timedelta(seconds=1))}"


def test_prefill_keys_match_tile_requests(cmr_client, store):
    """A tile request stores its parent search under a key the pre-fill computes."""
    cat = presets.catalog()
    t = utc(2024, 8, 27, 15, 0)
    for ds_id, ds in cat.datasets.items():
        if ds.backend not in CMR_BACKENDS:
            continue
        z = max(ds.minzoom, min(12, ds.maxzoom))
        tile = WEB_MERCATOR_TMS.tile(-72.93, 41.31, z)
        if isinstance(ds.time, GranuleTime):
            sent = [timeres.iso(t), website_datetime(ds.time, t)]
            values = prefill.datetimes(ds.time, t)
        else:
            sent, values = [None], [None]
        for render in ds.renders:
            for value in sent:
                store.items.clear()
                qs = f"?datetime={value}" if value else ""
                cmr_client.get(f"/datasets/{ds_id}/{render}/tiles/WebMercatorQuad/{z}/{tile.x}/{tile.y}.png{qs}")
                assert len(store.items) == 1, (ds_id, render, value)
                (item,) = store.items.values()
                planned = {
                    lookups.key(granules.KIND, q)
                    for q in prefill.queries(cat, ds_id, values, prefill.parent_tiles(ds, cat.aoi, [min(z, 8)]))
                }
                assert item["pk"] in planned, (ds_id, render, value, item["query"])


def test_prefill_skips_cached_and_unsettled(store, monkeypatch):
    searched = []
    monkeypatch.setattr(prefill, "granule_times", lambda ds, bbox, start, end: ([utc(2024, 8, 27, 15)], 0))
    monkeypatch.setattr(
        granules, "search_parent", lambda q, client=None: searched.append(q) or {"granules": [], "complete": True}
    )
    counts = prefill.prefill(store, ["hls-l30"], start=utc(2024, 8, 1), end=utc(2024, 9, 1))
    # the API's and the website's forms of a day are the same search
    assert counts["hls-l30"] == {"stored": 1} and len(searched) == 1
    assert prefill.prefill(store, ["hls-l30"], start=utc(2024, 8, 1), end=utc(2024, 9, 1))["hls-l30"] == {"cached": 1}

    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(prefill, "granule_times", lambda ds, bbox, start, end: ([now - dt.timedelta(days=1)], 0))
    assert prefill.prefill(store, ["hls-l30"], start=now - dt.timedelta(days=30), end=now)["hls-l30"] == {"recent": 1}


def test_dry_run_stores_nothing(store, monkeypatch):
    monkeypatch.setattr(prefill, "granule_times", lambda ds, bbox, start, end: ([utc(2024, 8, 27, 15)], 0))
    counts = prefill.prefill(None, ["hls-l30", "aster-gdem"], start=utc(2024, 8, 1), end=utc(2024, 9, 1))
    assert counts == {"hls-l30": {"planned": 1}, "aster-gdem": {"planned": 1}}
    assert not store.items


def test_tile_zooms():
    assert prefill._zooms("6-8") == [6, 7, 8]
    assert prefill._zooms("8") == [8]
    with pytest.raises(argparse.ArgumentTypeError):
        prefill._zooms("9")
