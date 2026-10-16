from urllib.parse import parse_qs, urlencode

import pytest

from ycgs_titiler import presets, timeres
from ycgs_titiler.router import PresetError, request_zoom, resolve

CAT = presets.load()
GOES_KEYS = (
    "ABI-L2-MCMIPC/2026/154/18/OR_ABI-L2-MCMIPC-M6_G19_s20261541756179_e20261541758552_c20261541759259.nc",
    "ABI-L2-MCMIPC/2026/154/18/OR_ABI-L2-MCMIPC-M6_G19_s20261541801179_e20261541803552_c20261541804265.nc",
    "ABI-L2-MCMIPC/2026/154/18/OR_ABI-L2-MCMIPC-M6_G19_s20261541806179_e20261541808552_c20261541809064.nc",
    "ABI-L2-CMIPC/2026/154/18/OR_ABI-L2-CMIPC-M6C02_G19_s20261541801179_e20261541803552_c20261541804265.nc",
    "ABI-L2-CMIPC/2026/154/18/OR_ABI-L2-CMIPC-M6C13_G19_s20261541801179_e20261541803552_c20261541804265.nc",
    "ABI-L2-LSTC/2026/154/18/OR_ABI-L2-LSTC-M6_G19_s20261541801179_e20261541803552_c20261541807089.nc",
)


@pytest.fixture(autouse=True)
def fake_goes_listing(monkeypatch):
    """GOES listing from a recorded set of keys, for any hour prefix."""

    def _list(bucket, prefix):
        return tuple(k for k in GOES_KEYS if k.startswith(prefix))

    monkeypatch.setattr(timeres, "_list", _list)
    timeres.clear_caches()
    yield
    timeres.clear_caches()


def q(resolved) -> dict[str, list[str]]:
    return parse_qs(urlencode(resolved.params), keep_blank_values=True)


def query(**kw) -> dict[str, list[str]]:
    return {k: v if isinstance(v, list) else [v] for k, v in kw.items()}


def test_every_render_resolves():
    for ds_id, ds in CAT.datasets.items():
        for name, render in ds.renders.items():
            extra = {"datetime2": ["2026-07-20T21:00:00"]} if render.two_times else {}
            dt = {"datetime": ["2026-06-03T18:00:00Z"]} if ds.time.kind == "scan" else {}
            r = resolve(CAT, ds_id, name, "tiles/WebMercatorQuad/10/304/382.png", {**dt, **extra})
            assert r.path == f"{ds.prefix}/tiles/WebMercatorQuad/10/304/382.png"
            assert r.params


# region nisar-zoom
def test_nisar_balanced_low_zoom_uses_frequency_b():
    r = resolve(CAT, "nisar-gcov", "balanced", "tiles/WebMercatorQuad/8/76/95.png", {})
    p = q(r)
    assert r.path == "/cmr/xarray/tiles/WebMercatorQuad/8/76/95.png"
    assert p["group"] == ["/science/LSAR/GCOV/grids/frequencyB"]
    assert p["variables"] == ["HHHH", "HVHV"]
    assert p["expression"] == ["10*log10(b1);10*log10(b2);10*log10(b1/b2)"]
    assert p["rescale"] == ["-20,0", "-30,5", "2,18"]
    assert p["temporal"] == ["2026-07-17T00:00:01Z/2026-07-17T23:59:59Z"]
    assert r.pinned


# endregion nisar-zoom


def test_nisar_high_zoom_and_date():
    r = resolve(CAT, "nisar-gcov", "vegetation", "tiles/WebMercatorQuad/12/1218/1530.png", query(datetime="2026-08-01"))
    p = q(r)
    assert p["group"] == ["/science/LSAR/GCOV/grids/frequencyA"]
    assert p["temporal"] == ["2026-08-01T00:00:01Z/2026-08-01T23:59:59Z"]
    assert p["expression"] == ["10*log10(b2);10*log10(b1);10*log10(b1/b2)"]


def test_retina_tiles_count_as_one_zoom_higher():
    assert request_zoom("tiles/WebMercatorQuad/9/1/1@2x.png", {}) == 10
    r = resolve(CAT, "nisar-gcov", "hh", "tiles/WebMercatorQuad/9/152/191@2x.png", {})
    assert q(r)["group"] == ["/science/LSAR/GCOV/grids/frequencyA"]


def test_bbox_zoom_from_resolution():
    # Greater New Haven, 0.26 deg wide at 512 px: 56.5 Web Mercator m per pixel, zoom 11.4
    z = request_zoom("bbox/-73.05,41.25,-72.79,41.36/512x217.tif", {})
    assert z == pytest.approx(11.435, abs=1e-3)
    # The same box in Web Mercator meters (x = lon * 111319.49) gives the same zoom
    x0, x1 = -73.05 * 111319.49079327357, -72.79 * 111319.49079327357
    z_3857 = request_zoom(f"bbox/{x0},5050000,{x1},5066000/512x217.tif", query(coord_crs="epsg:3857"))
    assert z_3857 == pytest.approx(z)
    r = resolve(CAT, "nisar-gcov", "raw", "bbox/-73.05,41.25,-72.79,41.36/40x17.tif", {})
    assert q(r)["group"] == ["/science/LSAR/GCOV/grids/frequencyB"]


def test_granule_ur_without_datetime_skips_default_temporal():
    r = resolve(CAT, "nisar-gcov", "hh", "tiles/WebMercatorQuad/10/304/382.png", query(granule_ur="NISAR_X"))
    p = q(r)
    assert p["granule_ur"] == ["NISAR_X"]
    assert "temporal" not in p


def test_smap_instant_granule_and_grouped_backend():
    r = resolve(CAT, "smap-l4", "rootzone", "tiles/WebMercatorQuad/6/19/23.png", query(datetime="2026-07-30T16:30"))
    p = q(r)
    assert r.path.startswith("/cmr/xarray-grouped/")
    assert p["temporal"] == ["2026-07-30T16:30:00Z"]
    assert p["group"] == ["Geophysical_Data"]
    assert p["variables"] == ["sm_rootzone"]


def test_hls_band_combinations():
    p = q(resolve(CAT, "hls-l30", "ndvi", "tiles/WebMercatorQuad/12/1218/1530.png", {}))
    assert p["assets"] == ["B05", "B04"]
    assert p["expression"] == ["(b1-b2)/(b1+b2)"]
    assert p["assets_regex"] == ["B[0-9][0-9]"]
    p = q(resolve(CAT, "hls-l30", "urban", "tiles/WebMercatorQuad/12/1218/1530.png", query(cloud_cover="0,20")))
    assert p["assets"] == ["B07", "B06", "B04"]
    assert p["cloud_cover"] == ["0,20"]


def test_user_overrides_render_scaling():
    p = q(resolve(CAT, "hls-l30", "truecolor", "tiles/WebMercatorQuad/12/1/1.png", query(rescale=["0,3000"] * 3)))
    assert p["rescale"] == ["0,3000"] * 3


def test_unknown_parameter_rejected():
    with pytest.raises(PresetError) as e:
        resolve(CAT, "hls-l30", "truecolor", "tiles/WebMercatorQuad/12/1/1.png", query(collection_concept_id="X"))
    assert e.value.status == 400
    with pytest.raises(PresetError) as e:  # variables only for raw
        resolve(CAT, "goes19-abi", "truecolor", "tiles/WebMercatorQuad/6/1/1.png", query(variables="CMI_C13"))
    when = "2026-06-03T18:00Z"
    p = q(
        resolve(CAT, "goes19-abi", "raw", "tiles/WebMercatorQuad/6/1/1.png", query(variables="CMI_C13", datetime=when))
    )
    assert p["variables"] == ["CMI_C13"]


def test_unknown_dataset_and_render():
    with pytest.raises(PresetError) as e:
        resolve(CAT, "nope", "x", "info", {})
    assert e.value.status == 404
    with pytest.raises(PresetError) as e:
        resolve(CAT, "goes19-abi", "nope", "info", {})
    assert e.value.status == 404


def test_era5_time_steps_are_lazy_sel():
    p = q(
        resolve(
            CAT, "era5-land-t2m", "celsius", "tiles/WebMercatorQuad/6/19/23.png", query(datetime="2026-07-20T09:00Z")
        )
    )
    assert p["sel"] == ["time=nearest::2026-07-20T09:00:00"]
    assert p["variables"] == ["t2m"]
    assert p["url"][0].endswith("timeChunked.zarr")
    p = q(
        resolve(
            CAT,
            "era5-land-t2m",
            "diff",
            "tiles/WebMercatorQuad/6/19/23.png",
            query(datetime="2026-07-20T09:00", datetime2="2026-07-20T17:00"),
        )
    )
    assert p["sel"] == ["time=nearest::2026-07-20T09:00:00", "time=nearest::2026-07-20T17:00:00"]
    assert p["expression"] == ["b2-b1"]
    with pytest.raises(PresetError):
        resolve(CAT, "era5-land-t2m", "diff", "tiles/WebMercatorQuad/6/19/23.png", query(datetime="2026-07-20T09:00"))


# region goes-scan
def test_goes_nearest_scan_and_render_specific_product():
    r = resolve(CAT, "goes19-abi", "truecolor", "tiles/WebMercatorQuad/6/19/23.png", query(datetime="2026-06-03T18:02"))
    assert q(r)["url"] == [f"s3://noaa-goes19/{GOES_KEYS[1]}"]
    assert r.time == "2026-06-03T18:01:17Z"
    assert r.pinned
    r = resolve(CAT, "goes19-abi", "red-500m", "tiles/WebMercatorQuad/9/1/1.png", query(datetime="2026-06-03T18:02"))
    assert q(r)["url"] == [f"s3://noaa-goes19/{GOES_KEYS[3]}"]
    assert q(r)["variables"] == ["CMI"]


# endregion goes-scan


def test_goes_latest_is_not_pinned(monkeypatch):
    latest = (timeres.parse_datetime("2026-06-03T18:06:17Z"), GOES_KEYS[2])
    monkeypatch.setattr(timeres, "scan_key", lambda spec, value: latest)
    r = resolve(CAT, "goes19-abi", "ir-clean", "tiles/WebMercatorQuad/6/19/23.png", {})
    assert not r.pinned
    assert q(r)["url"] == [f"s3://noaa-goes19/{GOES_KEYS[2]}"]


def test_list_scans_window():
    ds = CAT.datasets["goes19-abi"]
    out = timeres.list_scans(
        ds, timeres.parse_datetime("2026-06-03T18:00Z"), timeres.parse_datetime("2026-06-03T18:05Z")
    )
    assert [t["datetime"] for t in out] == ["2026-06-03T18:01:17Z"]
    with pytest.raises(timeres.TimeError):
        timeres.list_scans(ds, timeres.parse_datetime("2026-06-01"), timeres.parse_datetime("2026-06-04"))


def test_parse_datetime():
    assert timeres.iso(timeres.parse_datetime("2026-07-17")) == "2026-07-17T00:00:00Z"
    assert timeres.iso(timeres.parse_datetime("2026-07-17T10:00-04:00")) == "2026-07-17T14:00:00Z"
    with pytest.raises(timeres.TimeError):
        timeres.parse_datetime("yesterday")


def test_cmr_datasets_are_served_next_to_earthdata():
    assert all(ds.deployment == "nasa" for ds in CAT.datasets.values() if ds.backend.startswith("cmr-"))


# region new-time-kinds
def test_year_granules_skip_the_previous_years_granule():
    p = q(resolve(CAT, "viirs-blackmarble", "radiance", "tiles/WebMercatorQuad/9/152/191.png", query(datetime="2025")))
    # 2024's annual granule ends at 2025-01-01T00:00:00 (CMR ranges are inclusive)
    assert p["temporal"] == ["2025-01-01T00:00:01Z/2025-12-31T23:59:59Z"]
    assert p["group"] == ["HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"]


def test_interval_datetime_is_used_as_is():
    p = q(
        resolve(
            CAT, "smap-l4", "raw", "tiles/WebMercatorQuad/6/19/23.npy",
            query(datetime="2026-07-30T15:00:00Z/2026-07-30T17:59:59Z"),
        )
    )  # fmt: skip
    assert p["temporal"] == ["2026-07-30T15:00:01Z/2026-07-30T17:59:59Z"]


def test_template_time_fills_the_url():
    r = resolve(CAT, "chirps-daily", "precip", "tiles/WebMercatorQuad/6/19/23.png", query(datetime="2026-07-29T12:00Z"))
    assert r.path == "/cog/tiles/WebMercatorQuad/6/19/23.png"
    assert q(r)["url"] == [
        "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/sat/2026/chirps-v3.0.sat.2026.07.29.tif"
    ]
    assert r.time == "2026-07-29"


def test_template_times_stop_at_latency():
    spec = CAT.datasets["chirps-daily"].time
    times = timeres.list_template(spec, timeres.parse_datetime("2026-07-30"), timeres.parse_datetime("2026-08-02"))
    assert [t["datetime"] for t in times] == ["2026-07-30", "2026-07-31", "2026-08-01", "2026-08-02"]


def test_static_dataset_has_no_time():
    r = resolve(CAT, "aster-gdem", "raw", "tiles/WebMercatorQuad/10/304/381.npy", {})
    assert "temporal" not in q(r) and r.time is None
    assert q(r)["assets"] == ["dem"]


def test_goes_lst_scan():
    r = resolve(CAT, "goes19-lst", "raw", "tiles/WebMercatorQuad/6/19/23.npy", query(datetime="2026-06-03T18:00Z"))
    assert q(r)["url"][0].endswith("OR_ABI-L2-LSTC-M6_G19_s20261541801179_e20261541803552_c20261541807089.nc")
    assert q(r)["variables"] == ["LST", "DQF"]


def test_parse_year_and_month():
    assert timeres.iso(timeres.parse_datetime("2025")) == "2025-01-01T00:00:00Z"
    assert timeres.iso(timeres.parse_datetime("2026-07")) == "2026-07-01T00:00:00Z"


# endregion new-time-kinds
