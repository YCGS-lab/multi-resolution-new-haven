# /// script
# requires-python = ">=3.11"
# dependencies = ["sliderule", "geopandas", "pyarrow", "shapely", "numpy", "pandas", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ICESat-2 ATL08 canopy heights and ATL03 classified photons via SlideRule Earth.

Uses the public SlideRule cluster (slideruleearth.io, no credentials) and its
x-series endpoints:

1. `atl08x`: all ATL08 (release 007) land/vegetation segments intersecting the
   greater view (padded), for the growing season May-Sep of 2026 and 2025.
   ATL08 processing latency means 2026 has only data through mid-July (and
   only one pass with returns over New Haven), so 2025 is also downloaded.
   The 2019-2024 growing seasons are downloaded too (no 2025-2026 segment
   falls inside the central view).
   Written as GeoParquet:
     data/icesat2/atl08_<year>.parquet       100 m segments (h_canopy etc.)
     data/icesat2/atl08_20m_<year>.parquet   20 m sub-segments (h_canopy_20m)
2. Sample lines: 2-3 strong-beam 2025-2026 passes crossing the greater view, chosen from
   the ATL08 results (long, well-covered, distinct tracks, mixing urban and
   forest). For each, `atl03x` returns every ATL03 photon of that beam inside
   the view with its ATL08 photon class (noise/ground/canopy/top of canopy/
   unclassified):
     data/icesat2/lines.json                 the selected lines
     data/icesat2/atl03_line<n>.parquet      photons per line

Results are cached: delete a file to re-download it.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
import pandas as pd
from sliderule import sliderule

from common import config, views

DATASET = "icesat2"
OUT = config.data_dir(DATASET)
RECENT = (2026, 2025)  # the requested season, and the fallback (2026 is incomplete)
ARCHIVE = tuple(range(2024, 2018, -1))  # earlier growing seasons, for a multi-year product
SEASONS = {y: (f"{y}-05-01T00:00:00Z", f"{y}-09-30T23:59:59Z") for y in RECENT + ARCHIVE}
PAD_M = 300  # ATL08 segments are 100 m long; pad so partial segments at the frame are kept
GT_NAMES = {10: "gt1l", 20: "gt1r", 30: "gt2l", 40: "gt2r", 50: "gt3l", 60: "gt3r"}
STRONG_SPOTS = (1, 3, 5)
ATL08_FILL = 3.0e38  # float32 max (3.4028235e38) marks invalid 20 m values
N_LINES = 3
MIN_LINE_KM = 5.0


def region_poly(pad_m=PAD_M):
    """Counter-clockwise lon/lat polygon of the (padded) greater view."""
    w, s, e, n = views.VIEWS["greater"].bounds_lonlat(pad_m)
    return [dict(lon=w, lat=s), dict(lon=e, lat=s), dict(lon=e, lat=n), dict(lon=w, lat=n), dict(lon=w, lat=s)]


def add_track_info(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add granule name, beam name and strong/weak flag columns."""
    srctbl = gdf.attrs.get("meta", {}).get("srctbl", {})
    if "srcid" in gdf:
        gdf["granule"] = gdf["srcid"].astype(str).map(srctbl)
    gdf["beam"] = gdf["gt"].map(GT_NAMES)
    gdf["strong"] = gdf["spot"].isin(STRONG_SPOTS)
    return gdf


def explode_20m(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One row per ATL08 20 m sub-segment (5 per 100 m segment)."""
    keep = ["rgt", "cycle", "region", "gt", "spot", "beam", "strong", "granule", "segment_id_beg", "x_atc"]
    keep = [c for c in keep if c in gdf]
    base = pd.DataFrame(gdf[keep]).reset_index()
    rows = []
    for k in range(5):
        df = base.copy()
        df["sub"] = k
        df["latitude"] = [a[k] for a in gdf["latitude_20m"]]
        df["longitude"] = [a[k] for a in gdf["longitude_20m"]]
        df["h_canopy_20m"] = [a[k] for a in gdf["canopy/h_canopy_20m"]]
        df["h_te_best_fit_20m"] = [a[k] for a in gdf["terrain/h_te_best_fit_20m"]]
        rows.append(df)
    df = pd.concat(rows, ignore_index=True)
    for c in ("h_canopy_20m", "h_te_best_fit_20m"):
        df[c] = df[c].astype("float32").where(df[c] < ATL08_FILL)
    df = df[df["latitude"].abs() <= 90].sort_values(["time_ns", "sub"])
    out = gpd.GeoDataFrame(
        df.drop(columns=["latitude", "longitude"]),
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs="EPSG:4326",
    )
    return out.set_index("time_ns")


# region atl08x-segment-request
def download_atl08(year: int) -> gpd.GeoDataFrame:
    path = OUT / f"atl08_{year}.parquet"
    if path.exists():
        print(f"cached {path.relative_to(config.REPO)}")
        return gpd.read_parquet(path)
    t0, t1 = SEASONS[year]
    print(f"atl08x {t0} to {t1}")
    parms = {
        "poly": region_poly(),
        "t0": t0,
        "t1": t1,
        "atl08_fields": [
            "canopy/h_canopy_20m",
            "terrain/h_te_best_fit_20m",
            "latitude_20m",
            "longitude_20m",
        ],
    }
    gdf = sliderule.run("atl08x", parms)
    gdf = add_track_info(gdf)
    granules = sorted(set(gdf.attrs.get("meta", {}).get("srctbl", {}).values()))
    print(f"  {len(gdf)} segments from {gdf['granule'].nunique()} of {len(granules)} granules searched")
    meta = {"endpoint": "atl08x", "parms": parms, "granules_searched": granules}
    gdf.to_parquet(path)
    (OUT / f"atl08_{year}_request.json").write_text(json.dumps(meta, indent=2))
    explode_20m(gdf).to_parquet(OUT / f"atl08_20m_{year}.parquet")
    print(f"  wrote {path.relative_to(config.REPO)} and atl08_20m_{year}.parquet")
    return gdf
# endregion atl08x-segment-request


def candidates(atl08: gpd.GeoDataFrame) -> pd.DataFrame:
    """Per (granule, strong beam): coverage inside the greater and central views."""
    rows = []
    for (granule, beam), g in atl08[atl08["strong"]].groupby(["granule", "beam"]):
        stats = {}
        for name, view in views.VIEWS.items():
            xmin, ymin, xmax, ymax = view.bounds
            x, y = view.to_xy(g.geometry.x.values, g.geometry.y.values)
            m = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
            stats[f"n_{name}"] = int(m.sum())
            if name == "greater" and m.any():
                stats["span_km"] = round(np.hypot(np.ptp(x[m]), np.ptp(y[m])) / view.merc_scale / 1000, 2)
                stats["lon"] = round(float(g.geometry.x[m].mean()), 4)
                stats["frac_canopy"] = round(float(np.isfinite(g["h_canopy"][m]).mean()), 2)
                stats["frac_urban"] = round(float((g["segment_landcover"][m] == 50).mean()), 2)
        if stats["n_greater"]:
            rows.append(
                dict(
                    granule=granule, beam=beam, spot=int(g["spot"].iloc[0]), rgt=int(g["rgt"].iloc[0]),
                    cycle=int(g["cycle"].iloc[0]), date=str(g.index.min())[:19],
                    solar_elevation=round(float(g["solar_elevation"].mean()), 1), **stats,
                )
            )  # fmt: skip
    return pd.DataFrame(rows).sort_values("n_greater", ascending=False)


# region sample-line-selection
def select_lines(recent: gpd.GeoDataFrame, everything: gpd.GeoDataFrame) -> list[dict]:
    """Pick strong-beam sample lines crossing the greater view.

    Coverage score = number of 100 m ATL08 segments inside the greater view
    (~ km of track with returns x 10: long and mostly cloud-free); lines must
    span >= MIN_LINE_KM.
      - the best-covered line of each of the 2 best 2025-2026 passes;
      - the best-covered line crossing the central view (no 2025-2026 pass
        does), from any season, preferring night-time (less solar noise) and
        Jun-Sep (full leaf-on) acquisitions.
    Lines are numbered west to east.
    """
    rc = candidates(recent)
    print("2025-2026 candidate strong-beam lines:")
    print(rc.to_string(index=False))
    rc = rc[rc["span_km"] >= MIN_LINE_KM]
    chosen = rc.drop_duplicates("granule").head(N_LINES - 1)

    ac = candidates(everything)
    ac = ac[(ac["span_km"] >= MIN_LINE_KM) & (ac["n_central"] >= 10)]
    ac = ac.assign(
        night=ac["solar_elevation"] < 0, leaf_on=pd.to_datetime(ac["date"]).dt.month.between(6, 9)
    ).sort_values(["night", "leaf_on", "n_greater"], ascending=False)
    print("candidate strong-beam lines crossing the central view (all seasons):")
    print(ac.to_string(index=False))
    chosen = pd.concat([chosen, ac.drop(columns=["night", "leaf_on"]).head(1)]).sort_values("lon")
    return [dict(n=i + 1, **r) for i, r in enumerate(chosen.to_dict("records"))]
# endregion sample-line-selection


def download_photons(line: dict) -> None:
    path = OUT / f"atl03_line{line['n']}.parquet"
    if path.exists():
        print(f"cached {path.relative_to(config.REPO)}")
        return
    resource = line["granule"].replace("ATL08_", "ATL03_")
    print(f"atl03x line {line['n']}: {resource} {line['beam']}")
    parms = {
        "poly": region_poly(pad_m=0),  # the line = this beam's photons inside the greater view
        "beams": [line["beam"]],
        "srt": 0,  # land surface-type confidences
        "cnf": 0,  # keep all photons incl. background; ATL08 class says what they are
        "atl08_class": ["atl08_noise", "atl08_ground", "atl08_canopy", "atl08_top_of_canopy", "atl08_unclassified"],
        "datum": "EGM08",  # orthometric heights
    }
    gdf = sliderule.run("atl03x", parms, resources=[resource])
    gdf = add_track_info(gdf)
    print(f"  {len(gdf)} photons; classes: {gdf['atl08_class'].value_counts().sort_index().to_dict()}")
    gdf.to_parquet(path)


def main():
    sliderule.init(verbose=False)
    atl08 = {year: download_atl08(year) for year in SEASONS}
    recent = pd.concat([atl08[y] for y in RECENT])

    lines_path = OUT / "lines.json"
    if lines_path.exists():
        lines = json.loads(lines_path.read_text())
    else:
        lines = select_lines(recent, pd.concat(atl08.values()))
        lines_path.write_text(json.dumps(lines, indent=2))
    if "--atl08-only" in sys.argv:
        return
    for line in lines:
        print(f"line {line['n']}: {line['date']} RGT {line['rgt']} {line['beam']} ({line['span_km']} km)")
        download_photons(line)


if __name__ == "__main__":
    main()
