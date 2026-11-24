"""The fixed request set every variant is measured with.

For each dataset preset (datasets.yaml) at a pinned time: tiles over the
Greater New Haven AOI at four zoom levels between the preset's min and max
zoom (at most 6 tiles per zoom, those nearest the AOI centre), in
the preset's first styled render (PNG) and in `raw` (.npy, for the numeric
comparison). A few extra renders cover other code paths (GOES 0.5 km band,
ERA5 two-time difference).

    python requests.py            # prints the paths, one per line
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import morecantile
import yaml

CATALOG = Path(__file__).resolve().parents[3] / "src/ycgs_titiler/datasets.yaml"
TMS = morecantile.tms.get("WebMercatorQuad")

# Times for presets whose default is "latest" (would change between runs).
PINNED = {
    "goes19-abi": "2026-11-20T17:01:00Z",
    "goes19-lst": "2026-11-20T17:00:00Z",
}
EXTRA_RENDERS = {"goes19-abi": ["red-500m", "ir-clean"], "era5-land-t2m": ["diff"]}
TWO_TIMES = {"era5-land-t2m": "2026-07-19T17:00:00"}


def zooms(ds: dict) -> list[int]:
    lo, hi = max(ds.get("minzoom", 0), 5), min(ds.get("maxzoom", 14), 14)
    return sorted({round(lo + (hi - lo) * f) for f in (0, 1 / 3, 2 / 3, 1)})


def tiles(aoi, z: int) -> list[morecantile.Tile]:
    ts = list(TMS.tiles(*aoi, zooms=[z]))
    cx, cy = (aoi[0] + aoi[2]) / 2, (aoi[1] + aoi[3]) / 2
    c = TMS.tile(cx, cy, z)
    ts.sort(key=lambda t: (t.x - c.x) ** 2 + (t.y - c.y) ** 2)
    return sorted(ts[:6], key=lambda t: (t.x, t.y))


def build() -> list[dict]:
    cat = yaml.safe_load(CATALOG.read_text())
    aoi = cat["aoi"]
    out = []
    for ds_id, ds in cat["datasets"].items():
        styled = next(r for r in ds["renders"] if r != "raw")
        renders = [(styled, "png"), ("raw", "npy")] + [(r, "png") for r in EXTRA_RENDERS.get(ds_id, [])]
        for render, ext in renders:
            rds = {**ds, **ds["renders"][render]} if isinstance(ds["renders"][render], dict) else ds
            for z in zooms({**ds, "maxzoom": rds.get("maxzoom", ds.get("maxzoom"))}):
                for t in tiles(aoi, z):
                    q = {}
                    if ds_id in PINNED:
                        q["datetime"] = PINNED[ds_id]
                    if render == "diff":
                        q["datetime2"] = TWO_TIMES[ds_id]
                    path = f"/datasets/{ds_id}/{render}/tiles/WebMercatorQuad/{t.z}/{t.x}/{t.y}.{ext}"
                    if q:
                        path += "?" + urlencode(q)
                    out.append({"dataset": ds_id, "render": render, "z": t.z, "path": path})
    return out


if __name__ == "__main__":
    for r in build():
        print(r["path"])
