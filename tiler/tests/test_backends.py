"""YCGS_BACKENDS: a function serves (mounts and imports) only some backends
(terraform function_layout = "reader": COG and xarray datasets in separate functions)."""

import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from ycgs_titiler import presets
from ycgs_titiler.main import create_app
from ycgs_titiler.settings import settings


@pytest.fixture
def catalog(tmp_path, monkeypatch, era5_like):
    cat = {
        "aoi": [-73.05, 41.25, -72.79, 41.36],
        "datasets": {
            "t2m": {
                "title": "test",
                "deployment": "ecmwf",
                "backend": "xarray",
                "params": {"url": era5_like, "variables": ["2m_temperature"]},
                "time": {"kind": "dimension", "dim": "time", "default": "2026-07-20T12:00:00"},
                "renders": {"celsius": {"title": "C", "params": {"expression": "b1-273.15", "rescale": "0,30"}}},
            }
        },
    }
    path = tmp_path / "datasets.yaml"
    path.write_text(yaml.safe_dump(cat))
    monkeypatch.setenv("YCGS_DATASETS_FILE", str(path))
    presets.catalog.cache_clear()
    yield
    presets.catalog.cache_clear()


def paths(app) -> set[str]:
    return set(app.openapi()["paths"])


def test_all_backends_by_default(catalog, monkeypatch):
    monkeypatch.setattr(settings, "backends", "")
    app = create_app()
    assert {"/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}", "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}"} <= paths(app)


def test_cog_function_has_no_xarray_endpoints_and_refuses_xarray_presets(catalog, monkeypatch):
    monkeypatch.setattr(settings, "backends", "cog")
    app = create_app()
    assert not any(p.startswith("/xarray") for p in paths(app))
    assert any(p.startswith("/cog") for p in paths(app))
    client = TestClient(app)
    r = client.get("/datasets/t2m/celsius/tiles/WebMercatorQuad/9/150/190.png")
    assert r.status_code == 404
    assert "served by another function" in r.json()["detail"]
    assert client.get("/datasets/t2m/times").status_code == 404
    # catalog metadata is served everywhere
    assert client.get("/datasets/t2m").status_code == 200


def test_xarray_function_serves_its_presets(catalog, monkeypatch):
    monkeypatch.setattr(settings, "backends", "xarray")
    client = TestClient(create_app())
    r = client.get("/datasets/t2m/celsius/tiles/WebMercatorQuad/9/150/190.png?datetime=2026-07-20T05:00")
    assert r.status_code == 200, r.text
    assert not any(p.startswith("/cog") for p in paths(client.app))


def test_cog_function_does_not_import_the_xarray_readers():
    code = (
        "import sys; from ycgs_titiler.main import app; "
        "print(sorted(m for m in ('ycgs_titiler.readers', 'titiler.xarray.factory', 'zarr', 'h5py', 'obstore') "
        "if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={"YCGS_BACKENDS": "cog", "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "[]"
