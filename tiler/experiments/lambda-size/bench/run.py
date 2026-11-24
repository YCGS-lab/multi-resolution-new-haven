"""Benchmark one package variant in local Lambda containers, offline (snapshot proxy in replay mode).

    python run.py NAME --pkg tiler.zip [--pkg-for nasa=a.zip ...] [--cold 10] [--out DIR]
                  [--layout deployments|split]

Each deployment (nasa, noaa, ecmwf; with --layout split, each deployment and
reader type) gets its own function, with the memory set in
terraform/tiler/variables.tf (lambda_memory). Requests go to the function that
serves their dataset (datasets.yaml `deployment`, and with split the backend
type), as CloudFront routes them.

- cold: N times per function, a fresh container and one tile request; the
  init timings come from lambda_entry's log line (unpack, import), the first
  tile's time is measured here. The page cache is dropped before each start.
- warm: one container per function; the whole request set twice. Pass 1 is the
  first time each tile is asked for (datasets opened on first use), pass 2 the
  same requests again. Responses of pass 1 are saved for the output comparison.
- memory: the container's cgroup memory.peak after the warm passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import yaml
from lambda_run import LambdaContainer

sys.path.insert(0, str(Path(__file__).parent.parent / "variants"))
from fn_package import BACKENDS
from requests import CATALOG, build

MEMORY = {"nasa": 3008, "noaa": 2048, "ecmwf": 2048}
# Container memory caps: nasa's 3008 MB runs out on repeated NISAR tiles in every variant (the
# baseline too; see REPORT.md), so its containers get headroom; CPU still follows MEMORY.
LIMIT = {"nasa": int(os.environ.get("BENCH_NASA_LIMIT_MB", "4096"))}
RASTER_BACKENDS = {"cog", "cmr-rasterio"}
# the first tile of a cold start, per function
FIRST = {"nasa": "hls-l30", "noaa": "goes19-abi", "ecmwf": "era5-land-t2m",
         "nasa-raster": "hls-l30", "nasa-xarray": "smap-l4", "noaa-raster": "chirps-daily",
         "noaa-xarray": "goes19-abi", "ecmwf-xarray": "era5-land-t2m"}


def out_name(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def function_of(ds: dict, layout: str) -> str:
    if layout == "split":
        return f"{ds['deployment']}-{'raster' if ds['backend'] in RASTER_BACKENDS else 'xarray'}"
    return ds["deployment"]


def unzip(zip_path: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            z.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                os.chmod(dest / info.filename, mode)
    return dest


def drop_caches() -> None:
    subprocess.run(["sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"], capture_output=True, check=False)


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))] if xs else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--pkg", type=Path, help="zip used by every function")
    ap.add_argument("--pkg-for", action="append", default=[], help="FUNCTION=zip (V5/V6)")
    ap.add_argument("--layout", default="deployments", choices=["deployments", "split"])
    ap.add_argument("--cold", type=int, default=10)
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("BENCH_OUT", "results")))
    ap.add_argument("--only", nargs="*", help="datasets to run (default: all)")
    ap.add_argument("--passes", type=int, default=2, help="warm passes over the request set")
    ap.add_argument("--set-backends", action="store_true",
                    help="give each function its YCGS_BACKENDS (variants/fn_package.py BACKENDS), as V5/V6 deploy them")
    args = ap.parse_args()

    out = args.out / args.name
    (out / "responses").mkdir(parents=True, exist_ok=True)
    cat = yaml.safe_load(CATALOG.read_text())["datasets"]
    reqs = [r for r in build() if not args.only or r["dataset"] in args.only]
    by_fn: dict[str, list[dict]] = {}
    for r in reqs:
        by_fn.setdefault(function_of(cat[r["dataset"]], args.layout), []).append(r)

    pkgs = dict(p.split("=", 1) for p in args.pkg_for)
    work = Path(os.environ.get("BENCH_WORK", "/tmp/bench-work")) / args.name
    task_dirs = {}
    for fn in by_fn:
        z = Path(pkgs.get(fn) or pkgs.get(fn.split("-")[0]) or args.pkg)
        key = hashlib.sha1(str(z.resolve()).encode()).hexdigest()[:8]
        if key not in task_dirs:
            task_dirs[key] = unzip(z, work / key)
        task_dirs[fn] = task_dirs[key]

    result: dict = {"name": args.name, "layout": args.layout, "functions": {}}
    port = 9100
    for fn, fn_reqs in by_fn.items():
        mem = MEMORY[fn.split("-")[0]]
        res: dict = {"memory_mb": mem, "package": str(task_dirs[fn]), "cold": [], "warm": {}}
        fn_env = {"YCGS_BACKENDS": BACKENDS[fn]} if args.set_backends else {}
        res["env"] = fn_env
        pngs = [r for r in fn_reqs if r["path"].split("?")[0].endswith(".png")]
        first = next((r for r in pngs if r["dataset"] == FIRST[fn]), pngs[0])
        # region cold
        for i in range(args.cold):
            drop_caches()
            c = LambdaContainer(str(task_dirs[fn]), port, mem, name=f"bench-{fn}", extra_env=fn_env,
                                limit_mb=LIMIT.get(fn.split("-")[0]))
            t0 = time.perf_counter()
            try:
                c.start()
                r = c.invoke(first["path"])
            except Exception as e:  # noqa: BLE001  (init failed)
                (out / f"{fn}-cold-{i}.log").write_text(c.logs())
                c.stop()
                res["cold"].append({"status": 599, "error": str(e)})
                print(f"{args.name} {fn} cold {i}: failed: {e}", flush=True)
                continue
            total = time.perf_counter() - t0
            init = c.init_timings() or {}
            res["cold"].append({"status": r.status, "first_request_s": round(r.seconds, 3),
                                "start_to_response_s": round(total, 3), **init})
            if r.status != 200:
                res["cold"][-1]["error"] = r.body[:500].decode(errors="replace")
                (out / f"{fn}-cold-{i}.log").write_text(c.logs())
            c.stop()
            print(f"{args.name} {fn} cold {i}: {r.status} first {r.seconds:.2f}s init {init}", flush=True)
        # endregion cold
        # region warm
        c = LambdaContainer(str(task_dirs[fn]), port, mem, name=f"bench-{fn}", extra_env=fn_env,
                            limit_mb=LIMIT.get(fn.split("-")[0]))
        c.start()
        for p in range(1, args.passes + 1):
            rows = []
            for rq in fn_reqs:
                try:
                    r = c.invoke(rq["path"])
                except Exception as e:  # noqa: BLE001  (runtime killed: out of memory)
                    print(f"{args.name} {fn}: {rq['path']}: {e}; restarting the container", flush=True)
                    rows.append({"path": rq["path"], "dataset": rq["dataset"], "status": 599, "s": None,
                                 "bytes": 0, "error": str(e)})
                    (out / f"{fn}-crash-{p}.log").write_text(c.logs())
                    c.stop()
                    c.start()
                    continue
                rows.append({"path": rq["path"], "dataset": rq["dataset"], "status": r.status,
                             "s": round(r.seconds, 4), "bytes": len(r.body)})
                if p == 1:
                    if r.status == 200:
                        (out / "responses" / out_name(rq["path"])).write_bytes(r.body)
                    else:
                        rows[-1]["error"] = r.body[:300].decode(errors="replace")
            res["warm"][f"pass{p}"] = rows
            ok = [x["s"] for x in rows if x["status"] == 200]
            print(f"{args.name} {fn} pass {p}: {len(ok)}/{len(rows)} ok, p50 {pct(ok, .5):.3f}s "
                  f"p95 {pct(ok, .95):.3f}s", flush=True)
        res["peak_memory_mb"] = c.peak_memory_mb()
        (out / f"{fn}-warm.log").write_text(c.logs())
        c.stop()
        # endregion warm
        cold_ok = [x for x in res["cold"] if x["status"] == 200]
        res["summary"] = {
            "cold_first_request_median_s": statistics.median([x["first_request_s"] for x in cold_ok]) if cold_ok else None,
            "cold_init_median_s": statistics.median([x.get("unpack_s", 0) + x.get("import_s", 0) for x in cold_ok])
            if cold_ok and "import_s" in cold_ok[0] else None,
            "cold_unpack_median_s": statistics.median([x.get("unpack_s", 0) for x in cold_ok]) if cold_ok else None,
            **{f"{p}_{k}": v for p in res["warm"] for k, v in (
                ("ok", sum(1 for x in res["warm"][p] if x["status"] == 200)),
                ("n", len(res["warm"][p])),
                ("p50_s", pct([x["s"] for x in res["warm"][p] if x["status"] == 200], .5)),
                ("p95_s", pct([x["s"] for x in res["warm"][p] if x["status"] == 200], .95)))},
        }
        result["functions"][fn] = res
        (out / "result.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({fn: r["summary"] | {"peak_memory_mb": r["peak_memory_mb"]}
                      for fn, r in result["functions"].items()}, indent=1))


if __name__ == "__main__":
    main()
