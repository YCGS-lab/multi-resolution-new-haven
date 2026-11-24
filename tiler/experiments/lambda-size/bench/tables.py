"""Markdown tables for REPORT.md from the benchmark results.

    python tables.py BUILD_DIR RESULTS_DIR [MEMORY_DIR] > tables.md

BUILD_DIR: <variant>/tiler.zip and fn/<base>-<function>.zip; RESULTS_DIR:
<variant>/result.json (run.py) and compare.json (compare.py); MEMORY_DIR:
mem-<variant>/result.json (run.py --cold 0 --passes 2 with a high memory cap).
"""

from __future__ import annotations

import json
import statistics
import sys
import zipfile
from pathlib import Path

LIMIT = 250 * 2**20
SINGLE = ["p0", "v1", "v2", "v3", "v4", "vf"]
LABEL = {
    "p0": "P0: PR #6 (deps.tar.zst, unpacked at init)",
    "v1": "V1: trim the wheels",
    "v2": "V2: + one copy of shared libraries",
    "v3": "V3: + numpy without BLAS",
    "v4": "V4: + GDAL/PROJ from source",
    "vf": "Chosen: V1 + numpy without BLAS (tiler/Dockerfile)",
    "v5-v1": "V5 on V1: package per deployment",
    "v5-v4": "V5 on V4",
    "v6-v1": "V6 on V1: function per reader type",
    "v6-v4": "V6 on V4",
}


def unzipped(z: Path) -> tuple[float, float]:
    with zipfile.ZipFile(z) as f:
        return sum(i.file_size for i in f.infolist()) / 2**20, z.stat().st_size / 2**20


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def fmt(x, nd=2, unit=""):
    return "–" if x is None else f"{x:.{nd}f}{unit}"


def main() -> None:
    build, res = Path(sys.argv[1]), Path(sys.argv[2])
    mem = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    out = []
    # region sizes
    out.append("| Variant | Unzipped MB | Zipped MB | Headroom under 250 MB |")
    out.append("|---|---:|---:|---:|")
    for v in SINGLE:
        u, zp = unzipped(build / v / "tiler.zip")
        if v == "p0":
            with zipfile.ZipFile(build / v / "tiler.zip") as f:
                tar = f.getinfo("deps.tar.zst").file_size / 2**20
            out.append(f"| {LABEL[v]} | {u:.1f} (deps.tar.zst {tar:.0f} MB; ~325 MB after unpacking) | {zp:.1f} | – |")
        else:
            out.append(f"| {LABEL[v]} | {u:.1f} | {zp:.1f} | {(250 - u) / 250:.0%} |")
    out.append("")
    out.append("| Function package | on V1: unzipped MB | on V4: unzipped MB |")
    out.append("|---|---:|---:|")
    for fn in ["nasa", "noaa", "ecmwf", "nasa-raster", "nasa-xarray", "noaa-raster", "noaa-xarray", "ecmwf-xarray"]:
        a, b = (unzipped(build / "fn" / f"{base}-{fn}.zip")[0] for base in ("v1", "v4"))
        out.append(f"| {('V5 ' if '-' not in fn else 'V6 ') + fn} | {a:.1f} | {b:.1f} |")
    out.append("")
    # endregion sizes
    # region timings
    out.append("| Variant | Function | Memory MB | Cold: init s (unpack + import) | Cold: first tile s | "
               "Warm pass 1 p50 / p95 s | Pass 2 p50 / p95 s | OK |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for d in sorted(res.iterdir()):
        if not (d / "result.json").exists() or d.name not in LABEL:
            continue
        r = json.loads((d / "result.json").read_text())
        for fn, x in r["functions"].items():
            cold = [c for c in x["cold"] if c["status"] == 200]
            unpack = med([c.get("unpack_s") for c in cold])
            imp = med([c.get("import_s") for c in cold])
            init = None if imp is None else (unpack or 0) + imp
            s = x["summary"]
            ok = f"{s['pass1_ok'] + s['pass2_ok']}/{s['pass1_n'] + s['pass2_n']}"
            out.append(
                f"| {d.name} | {fn} | {x['memory_mb']} | {fmt(init)} ({fmt(unpack)} + {fmt(imp)}) | "
                f"{fmt(med([c['first_request_s'] for c in cold]))} | {fmt(s['pass1_p50_s'], 3)} / "
                f"{fmt(s['pass1_p95_s'], 3)} | {fmt(s['pass2_p50_s'], 3)} / {fmt(s['pass2_p95_s'], 3)} | {ok} |")
    out.append("")
    # endregion timings
    # region memory
    if mem is not None:
        out.append("| Variant | nasa peak MB (setting 3008) | noaa peak MB (2048) | ecmwf peak MB (2048) |")
        out.append("|---|---:|---:|---:|")
        for v in SINGLE:
            f = mem / f"mem-{v}" / "result.json"
            if f.exists():
                r = json.loads(f.read_text())["functions"]
                out.append(f"| {v} | " + " | ".join(fmt(r[fn].get("peak_memory_mb"), 0) for fn in ("nasa", "noaa", "ecmwf"))
                           + " |")
        out.append("")
    # endregion memory
    # region outputs
    out.append("| Variant | Responses identical to P0 | Different | Missing | Largest difference (.npy) |")
    out.append("|---|---:|---:|---:|---|")
    for d in sorted(res.iterdir()):
        c = d / "compare.json"
        if not c.exists() or d.name not in LABEL:
            continue
        cmp = json.loads(c.read_text())
        rows = cmp["rows"]
        ident = sum(1 for r in rows if r.get("identical"))
        miss = sum(1 for r in rows if "missing" in r)
        diff = len(rows) - ident - miss
        worst = max((r.get("max_abs_diff", 0) for r in rows if not r.get("identical") and "missing" not in r),
                    default=None)
        out.append(f"| {d.name} | {ident} | {diff} | {miss} | {fmt(worst, 6) if diff else '–'} |")
    # endregion outputs
    print("\n".join(out))


if __name__ == "__main__":
    main()
