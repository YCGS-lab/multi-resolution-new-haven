import base64
import json
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from ycgs_titiler import presets
from ycgs_titiler.main import create_app
from ycgs_titiler.settings import settings


@pytest.fixture
def client(tmp_path, monkeypatch, era5_like):
    """App with a one-dataset catalog pointing at a local Zarr, behind the CloudFront secret."""
    catalog = {
        "aoi": [-73.05, 41.25, -72.79, 41.36],
        "datasets": {
            "t2m": {
                "title": "test",
                "deployment": "ecmwf",
                "backend": "xarray",
                "params": {"url": era5_like, "variables": ["2m_temperature"]},
                "time": {"kind": "dimension", "dim": "time", "default": "2026-07-20T12:00:00"},
                "renders": {
                    "celsius": {"title": "C", "params": {"expression": "b1-273.15", "rescale": "0,30"}},
                    "diff": {"title": "d", "params": {"expression": "b2-b1"}, "two_times": True},
                },
            }
        },
    }
    path = tmp_path / "datasets.yaml"
    path.write_text(yaml.safe_dump(catalog))
    monkeypatch.setenv("YCGS_DATASETS_FILE", str(path))
    monkeypatch.setattr(settings, "origin_verify", "s3cret")
    presets.catalog.cache_clear()
    yield TestClient(create_app(), headers={"x-origin-verify": "s3cret"})
    presets.catalog.cache_clear()


# region origin-verify
def test_requests_without_cloudfront_secret_are_rejected(client):
    r = client.get("/healthz", headers={"x-origin-verify": "wrong"})
    assert r.status_code == 403


# endregion origin-verify


def test_preset_tile_cache_and_time_headers(client):
    r = client.get("/datasets/t2m/celsius/tiles/WebMercatorQuad/9/150/190.png?datetime=2026-07-20T05:00")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.headers["x-ycgs-datetime"] == "2026-07-20T05:00"


def test_preset_errors_are_not_cached(client):
    r = client.get("/datasets/t2m/diff/tiles/WebMercatorQuad/9/150/190.png")
    assert r.status_code == 400
    assert r.headers["cache-control"] == "no-store"


def test_preset_point_value(client):
    r = client.get("/datasets/t2m/diff/point/-73.0,41.3?datetime=2026-07-20T06:00&datetime2=2026-07-20T09:00")
    assert r.status_code == 200, r.text
    assert r.json()["values"] == [pytest.approx(3.0)]


def test_tilejson_uses_cloudfront_host(client):
    r = client.get(
        "/datasets/t2m/celsius/WebMercatorQuad/tilejson.json?datetime=2026-07-20T05:00",
        headers={"x-ycgs-host": "tiles.example.org"},
    )
    assert r.status_code == 200
    assert r.json()["tiles"][0].startswith(
        "https://tiles.example.org/datasets/t2m/celsius/tiles/WebMercatorQuad/{z}/{x}/{y}.png?datetime="
    )


def test_catalog_and_times(client):
    assert client.get("/datasets").json()["t2m"]["deployment"] == "ecmwf"
    r = client.get("/datasets/t2m/times?start=2026-07-20T10:00&end=2026-07-20T12:00")
    assert r.status_code == 200, r.text
    assert [t["datetime"] for t in r.json()["times"]] == [
        "2026-07-20T10:00:00Z",
        "2026-07-20T11:00:00Z",
        "2026-07-20T12:00:00Z",
    ]


def test_xarray_endpoint_multi_variable(client, multivar_nc):
    r = client.get(
        "/xarray/point/-72.9,41.3", params={"url": multivar_nc, "variables": ["a", "b"], "expression": "b1*b2"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["values"] == [pytest.approx(4.0)]


def test_cmr_mount_includes_grouped_backend(monkeypatch):
    monkeypatch.setenv("TITILER_CMR_EARTHDATA_USERNAME", "user")
    monkeypatch.setenv("TITILER_CMR_EARTHDATA_PASSWORD", "pass")
    monkeypatch.setattr(settings, "features", "cmr")
    monkeypatch.setattr(settings, "origin_verify", None)
    client = TestClient(create_app())
    paths = client.get("/cmr/api").json()["paths"]
    assert "/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}" in paths
    assert "/xarray-grouped/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}" in paths
    assert "/rasterio/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}" in paths
    TestClient(create_app())  # creating the app again doesn't register the routes twice


def jwt(payload: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc(payload)}.sig"


def test_cmr_with_earthdata_token(monkeypatch):
    from titiler.cmr import main as cmr

    monkeypatch.delenv("TITILER_CMR_EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("TITILER_CMR_EARTHDATA_PASSWORD", raising=False)
    monkeypatch.setenv("YCGS_EARTHDATA_TOKEN", jwt({"uid": "x", "exp": time.time() + 3600}))
    monkeypatch.setattr(settings, "features", "cmr")
    monkeypatch.setattr(settings, "origin_verify", None)
    client = TestClient(create_app())
    assert client.get("/cmr/api").status_code == 200
    provider = cmr.app.state.earthdata_token_provider
    assert provider() == os.environ["YCGS_EARTHDATA_TOKEN"]


def test_expired_earthdata_token():
    from fastapi import HTTPException

    from ycgs_titiler.main import StaticToken, jwt_expiry

    assert jwt_expiry("not-a-jwt") is None
    with pytest.raises(HTTPException) as e:
        StaticToken(jwt({"exp": 1_700_000_000}))()
    assert e.value.status_code == 503 and "expired on 2023-11-14" in e.value.detail


@pytest.mark.live
def test_live_goes_tile():
    """Real GOES-19 scan from the public NOAA bucket (pytest -m live)."""
    monkeypatch_free = TestClient(create_app())
    r = monkeypatch_free.get(
        "/datasets/goes19-abi/truecolor/tiles/WebMercatorQuad/6/18/23.png?datetime=2026-06-03T18:00Z"
    )
    assert r.status_code == 200, r.text
    assert r.headers["x-ycgs-datetime"] == "2026-06-03T18:01:17Z"
