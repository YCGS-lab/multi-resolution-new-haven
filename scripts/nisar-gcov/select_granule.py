# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "shapely", "earthaccess", "h5py"]
# ///
"""Pick the NISAR L2 GCOV (provisional) granule used by visualize-remote.py.

Searches CMR for GCOV granules over the views in July-August 2026 (falling
back to June / September 2026) and keeps those that are
  - dual-pol (HH + HV) in frequency A, full frames,
  - footprints containing both views with >= MIN_MARGIN_KM to spare
    (so a single frame covers everything; no mosaicking),
  - the latest processing version of each acquisition,
  - ascending passes (~05:50-06:00 local time): in the descending passes
    (~19:50 local) the harbor and Long Island Sound are wind-roughened and
    bright, which hides the coastline, while the morning passes show calm,
    dark water.
Among these, the driest acquisition wins (least ERA5 precipitation at New
Haven in the 72 h before, from the Open-Meteo archive API; wet soil and
canopy raise backscatter), ties broken by margin. The winner's valid-data
coverage of the views is checked through titiler-cmr, and its grid and
geometry (posting, CRS, look direction, incidence angle and azimuth time at
the view center) are read from the HDF5 metadata.

Writes data/nisar-gcov/granule.json.
"""

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import earthaccess
import h5py
import numpy as np
import requests
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.ops import transform as shp_transform

import granule as gr
from common import config, views

SEARCH_WINDOWS = [("2026-07-01", "2026-08-31"), ("2026-06-01", "2026-09-30")]
PAD_M = 100.0
MIN_MARGIN_KM = 5.0
WANT_PASS = "ASCENDING"
OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
COVERAGE_CHECK_M = 40.0  # pixel size of the quick valid-data check
UTM_CRS = "EPSG:32618"  # for footprint margins (New Haven is in UTM 18N)


def attrs(umm: dict) -> dict:
    return {a["Name"]: a["Values"] for a in umm.get("AdditionalAttributes", [])}


def footprint(umm: dict) -> Polygon:
    polys = umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"]
    out = None
    for gp in polys:
        p = Polygon([(q["Longitude"], q["Latitude"]) for q in gp["Boundary"]["Points"]])
        out = p if out is None else out.union(p)
    return out


# region driest-acquisition
def precipitation(start: str, end: str) -> tuple[list, list]:
    """Hourly ERA5 precipitation (mm) at the greater view center."""
    v = views.VIEWS["greater"]
    r = requests.get(
        OPEN_METEO,
        params=dict(latitude=v.lat, longitude=v.lon, start_date=start, end_date=end, hourly="precipitation", timezone="UTC"),
        timeout=120,
    )
    r.raise_for_status()
    h = r.json()["hourly"]
    return [dt.datetime.fromisoformat(t) for t in h["time"]], [p or 0.0 for p in h["precipitation"]]


def precip_before(times, precip, when: dt.datetime, hours: int) -> float:
    return float(sum(p for t, p in zip(times, precip) if when - dt.timedelta(hours=hours) <= t <= when))
# endregion driest-acquisition


def candidates(window) -> list[dict]:
    w, s, e, n = views.all_bounds_lonlat(PAD_M)
    to_utm = Transformer.from_crs("EPSG:4326", UTM_CRS, always_xy=True).transform
    aoi = box(w, s, e, n)
    aoi_utm = shp_transform(to_utm, aoi)
    results = earthaccess.search_data(
        concept_id=gr.COLLECTION_CONCEPT_ID, bounding_box=(w, s, e, n), temporal=(window[0], window[1] + "T23:59:59Z")
    )
    print(f"{len(results)} granules {window[0]} .. {window[1]}")
    times, precip = precipitation(window[0], window[1])
    by_acq = {}
    for res in results:
        umm = res["umm"]
        a = attrs(umm)
        ur = umm["GranuleUR"]
        start = umm["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        fp = footprint(umm)
        # distance from the views to the footprint edge
        margin_km = shp_transform(to_utm, fp).exterior.distance(aoi_utm) / 1000 if fp.contains(aoi) else 0.0
        t = dt.datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None)
        c = {
            "granule_ur": ur,
            "start": start,
            "end": umm["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
            "pass": a.get("ASCENDING_DESCENDING", ["?"])[0],
            "track": int(a.get("TRACK_NUMBER", ["-1"])[0]),
            "frame": int(a.get("FRAME_NUMBER", ["-1"])[0]),
            "full_frame": a.get("FULL_FRAME", ["FALSE"])[0] == "TRUE",
            "pols_a": a.get("FREQUENCY_A_POLARIZATION", []),
            "bandwidth_a_mhz": float(a.get("FREQUENCY_A_RANGE_BANDWIDTH", ["nan"])[0]),
            "absolute_orbit": umm.get("OrbitCalculatedSpatialDomains", [{}])[0].get("OrbitNumber"),
            "covers_views": fp.contains(aoi),
            "margin_km": round(margin_km, 1),
            "precip_24h_mm": round(precip_before(times, precip, t, 24), 1),
            "precip_72h_mm": round(precip_before(times, precip, t, 72), 1),
            "size_mb": round(sum(f.get("SizeInBytes", 0) for f in umm["DataGranule"]["ArchiveAndDistributionInformation"] if f["Name"].endswith(".h5")) / 1e6),  # fmt: skip
        }
        # region granule-filtering
        # Same acquisition reprocessed: GranuleUR differs only in the trailing version counter.
        key = (c["track"], c["frame"], start)
        if key not in by_acq or ur > by_acq[key]["granule_ur"]:
            by_acq[key] = c
    out = sorted(by_acq.values(), key=lambda c: c["start"])
    for c in out:
        reasons = []
        if not {"HH", "HV"} <= set(c["pols_a"]):
            reasons.append("not dual-pol")
        if not c["full_frame"]:
            reasons.append("partial frame")
        if not c["covers_views"] or c["margin_km"] < MIN_MARGIN_KM:
            reasons.append("does not cover views")
        if c["pass"] != WANT_PASS:
            reasons.append(c["pass"].lower())
        c["rejected"] = ", ".join(reasons)
        print(
            f"  {c['start'][:16]} {c['pass'][:4]} track {c['track']:3d} frame {c['frame']:3d} margin {c['margin_km']:5.1f} km "
            f"precip 24h {c['precip_24h_mm']:4.1f} 72h {c['precip_72h_mm']:4.1f} mm  {c['rejected'] or 'OK'}"
        )
    ok = [c for c in out if not c["rejected"]]
    return sorted(ok, key=lambda c: (c["precip_72h_mm"], -c["margin_km"]))
        # endregion granule-filtering


def valid_fraction(c: dict) -> float:
    """Fraction of the (padded) views with valid HH and HV, at COVERAGE_CHECK_M pixels."""
    b = gr.snap_bounds(views.all_bounds_in(UTM_CRS, PAD_M), COVERAGE_CHECK_M)
    arr = gr.fetch_covariance(c["granule_ur"], b, UTM_CRS, COVERAGE_CHECK_M)
    return float(np.mean(np.all(np.isfinite(arr), axis=0)))


def _str(v) -> str:
    v = v[()] if isinstance(v, h5py.Dataset) else v
    return v.decode() if isinstance(v, bytes) else str(v)


def h5_metadata(granule_ur: str) -> dict:
    """Grid and geometry from the GCOV HDF5 (metadata only; a few MB of ranged reads)."""
    res = earthaccess.search_data(granule_ur=granule_ur, short_name=gr.SHORT_NAME)
    url = next(u for u in res[0].data_links() if u.endswith(".h5"))
    fs = earthaccess.get_fsspec_https_session()
    v = views.VIEWS["greater"]
    with fs.open(url, block_size=2 * 1024 * 1024, cache_type="blockcache") as f, h5py.File(f, "r") as h:
        fa = h[gr.GROUP]
        epsg = int(fa["projection"][()])
        dx, dy = float(fa["xCoordinateSpacing"][()]), float(fa["yCoordinateSpacing"][()])
        x0, y0 = float(fa["xCoordinates"][0]), float(fa["yCoordinates"][0])  # pixel centers
        fb = h[gr.GROUP.replace("frequencyA", "frequencyB")]
        idn = h["/science/LSAR/identification"]
        rtc = h["/science/LSAR/GCOV/metadata/processingInformation/parameters/rtc"]
        rg = h["/science/LSAR/GCOV/metadata/radarGrid"]
        cx, cy = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(v.lon, v.lat)
        ix = int(np.argmin(np.abs(rg["xCoordinates"][:] - cx)))
        iy = int(np.argmin(np.abs(rg["yCoordinates"][:] - cy)))
        iz = int(np.argmin(np.abs(rg["heightAboveEllipsoid"][:] - 0.0)))
        inc = float(rg["incidenceAngle"][iz, iy, ix])
        az = float(rg["zeroDopplerAzimuthTime"][iz, iy, ix])
        epoch = _str(rg["zeroDopplerAzimuthTime"].attrs["units"]).replace("seconds since ", "")
        az_time = dt.datetime.fromisoformat(epoch) + dt.timedelta(seconds=az)
        return {
            "crs": f"EPSG:{epsg}",
            "posting_m": abs(dx),
            "posting_b_m": abs(float(fb["xCoordinateSpacing"][()])),
            "grid_origin": [x0 - dx / 2, y0 - dy / 2],  # a pixel-edge corner of the native grid
            "look_direction": _str(idn["lookDirection"]),
            "orbit_pass_direction": _str(idn["orbitPassDirection"]),
            "product_version": _str(idn["productVersion"]),
            "composite_release_id": _str(idn["compositeReleaseId"]),
            "product_doi": _str(idn["productDoi"]),
            "backscatter": f"{_str(rtc['outputBackscatterNormalizationConvention'])}, "
            f"{_str(rtc['outputBackscatterExpressionConvention']).lower()} (RTC)",
            "incidence_angle_deg": round(inc, 1),
            "time_at_view_center_utc": az_time.isoformat(timespec="seconds"),
        }


def main():
    earthaccess.login(strategy="netrc")
    for window in SEARCH_WINDOWS:
        for c in candidates(window):
            frac = valid_fraction(c)
            print(f"{c['granule_ur']}: valid fraction over views {frac:.4f}")
            if frac < 0.999:
                continue
            meta = h5_metadata(c["granule_ur"])
            sel = {
                "granule_ur": c["granule_ur"],
                "collection_concept_id": gr.COLLECTION_CONCEPT_ID,
                "short_name": gr.SHORT_NAME,
                **{k: v for k, v in c.items() if k not in ("granule_ur", "rejected", "covers_views")},
                "valid_fraction": round(frac, 4),
                **meta,
                "selection": f"{window[0]}..{window[1]}, {WANT_PASS.lower()}, full frame, HH+HV, "
                "least 72 h precipitation (Open-Meteo ERA5)",
            }
            out = config.data_dir(gr.DATASET) / "granule.json"
            out.write_text(json.dumps(sel, indent=2) + "\n")
            print(json.dumps(sel, indent=2))
            print(f"selected {c['granule_ur']} -> {out.relative_to(config.REPO)}")
            return
    raise SystemExit("no granule passed the criteria")


if __name__ == "__main__":
    main()
