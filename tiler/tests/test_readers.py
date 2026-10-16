import numpy as np
import pytest
import xarray as xr

from ycgs_titiler import readers
from ycgs_titiler.readers import MultiVarReader, URLNotAllowed, fix_goes, get_variables, open_dataset_with_root_coords


# region two-times
def test_time_steps_become_bands_and_expression(era5_like):
    sel = ["time=nearest::2026-07-20T09:10:00", "time=nearest::2026-07-20T17:00:00"]
    with MultiVarReader(era5_like, variables=["2m_temperature"], sel=sel, expression="b2-b1") as r:
        assert r.input.dims == ("y", "x")
        img = r.part((-73.5, 41.2, -72.5, 41.6), dst_crs="epsg:4326", bounds_crs="epsg:4326", width=10, height=4)
    assert np.allclose(img.data, 8.0)  # 17:00 - 09:00 = 8 K


# endregion two-times


def test_single_time_step_in_celsius(era5_like):
    with MultiVarReader(
        era5_like, variables=["2m_temperature"], sel=["time=nearest::2026-07-20T05:00:00"], expression="b1-273.15"
    ) as r:
        img = r.tile(150, 190, 9)
    valid = img.array.compressed()
    assert valid.size and np.allclose(valid, 290 + 5 - 273.15)


def test_unselected_time_dimension_is_an_error(era5_like):
    with pytest.raises(ValueError, match="sel"):
        MultiVarReader(era5_like, variables=["2m_temperature", "2m_temperature"])


def test_multiple_variables_stack_into_bands(multivar_nc):
    with MultiVarReader(multivar_nc, variables=["a", "b"], expression="b1/b2;b1-b2") as r:
        assert r.input.sizes["band"] == 2
        img = r.part((-73.2, 41.0, -72.6, 41.5), dst_crs="epsg:4326", bounds_crs="epsg:4326", width=7, height=6)
    assert np.allclose(img.data[0], 4.0) and np.allclose(img.data[1], 3.0)


def test_missing_variable(multivar_nc):
    with pytest.raises(KeyError, match="not found"):
        MultiVarReader(multivar_nc, variables=["nope"])


def test_url_allowlist(monkeypatch):
    monkeypatch.setenv("YCGS_ALLOWED_URL_PREFIXES", "s3://noaa-goes19/")
    with pytest.raises(URLNotAllowed):
        readers.open_dataset("https://evil.example.com/data.zarr")
    with pytest.raises(URLNotAllowed):
        readers.open_dataset("s3://noaa-goes19-not-really/x.nc")


def test_cds_key_only_sent_to_cds_host(monkeypatch):
    monkeypatch.delenv("YCGS_CDS_API_KEY", raising=False)
    with pytest.raises(readers.MissingCredentials):
        readers._store("https://arco.datastores.ecmwf.int/x.zarr")
    readers._store("https://example.com/x.zarr")  # no key needed elsewhere


def test_goes_fixed_grid_to_meters():
    h = 35786023.0
    proj = {
        "grid_mapping_name": "geostationary", "perspective_point_height": h, "semi_major_axis": 6378137.0,
        "semi_minor_axis": 6356752.31414, "inverse_flattening": 298.2572221, "latitude_of_projection_origin": 0.0,
        "longitude_of_projection_origin": -75.0, "sweep_angle_axis": "x",
    }  # fmt: skip
    ds = xr.Dataset(
        {"CMI_C13": (("y", "x"), np.ones((3, 4), "float32")), "goes_imager_projection": ((), 0, proj)},
        coords={"x": [-0.1, -0.05, 0.0, 0.05], "y": [0.1, 0.05, 0.0]},
    )
    out = fix_goes(ds)
    assert np.isclose(float(out.x[0]), -0.1 * h)
    assert out.rio.crs.to_dict()["proj"] == "geos"
    da = get_variables(out, ["CMI_C13"])
    assert da.rio.crs.to_dict()["proj"] == "geos"


def test_group_without_coordinates_gets_root_coordinates(tmp_path, monkeypatch):
    """Like SMAP L4: data in /Geophysical_Data, x/y and the EASE-Grid 2.0 mapping at the root."""
    path = tmp_path / "smap.h5"
    x = np.array([-100.0, 0.0, 100.0, 200.0]) * 9008.055210146
    y = np.array([100.0, 0.0, -100.0]) * 9008.055210146
    ease = {
        "grid_mapping_name": "lambert_cylindrical_equal_area", "standard_parallel": 30.0,
        "longitude_of_central_meridian": 0.0, "false_easting": 0.0, "false_northing": 0.0,
    }  # fmt: skip
    xr.Dataset({"EASE2_global_projection": ((), 0, ease)}, coords={"x": x, "y": y}).to_netcdf(path, engine="h5netcdf")
    xr.Dataset({"sm_rootzone": (("y", "x"), np.full((3, 4), 0.3, "float32"))}).to_netcdf(
        path, group="Geophysical_Data", mode="a", engine="h5netcdf"
    )

    def fake_open(src_path, group=None, **kw):
        return xr.open_dataset(src_path, group=group, engine="h5netcdf", decode_coords="all")

    monkeypatch.setattr(readers, "cmr_open_dataset", fake_open)
    ds = open_dataset_with_root_coords(str(path), group="Geophysical_Data", auth_token="t")
    assert np.allclose(ds.x, x) and np.allclose(ds.y, y)
    assert ds.rio.crs.to_dict()["proj"] == "cea"
    from titiler.cmr.reader import get_variables as cmr_get_variables

    da = cmr_get_variables(ds, ["sm_rootzone"])
    assert da.rio.crs.to_dict()["proj"] == "cea"


# region latlon-grid
def test_latlon_variables_become_a_geographic_grid():
    """HDF-EOS5 geographic grid (VNP46A4): 1-D lat/lon variables giving cell upper-left corners."""
    import numpy as np
    import xarray as xr

    from ycgs_titiler.readers import latlon_grid

    res = 1 / 240
    lat = 50.0 - res * np.arange(4)
    lon = -80.0 + res * np.arange(5)
    ds = xr.Dataset(
        {
            "radiance": (("phony_dim_0", "phony_dim_1"), np.arange(20, dtype="float32").reshape(4, 5)),
            "lat": (("phony_dim_0",), lat),
            "lon": (("phony_dim_2",), lon),
        }
    )
    g = latlon_grid(ds)
    assert list(g.data_vars) == ["radiance"]
    assert g["radiance"].dims == ("y", "x")
    assert g.rio.crs.to_epsg() == 4326
    np.testing.assert_allclose(g.y.values, lat - res / 2)
    np.testing.assert_allclose(g.x.values, lon + res / 2)


# endregion latlon-grid
