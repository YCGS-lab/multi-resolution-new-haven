"""Which distributions and shared libraries the request set actually loads.

    python trace.py OUT.json [--datasets id ...]

Runs the requests in-process (snapshot proxy in replay mode, same environment
as record.py; YCGS_BACKENDS limits the app as in a split function), then lists
the distributions with at least one imported module, and every shared object
mapped into the process (/proc/self/maps).
"""

from __future__ import annotations

import importlib.metadata as md
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import env

env.apply(os.environ)

from fastapi.testclient import TestClient
from requests import build

from ycgs_titiler.main import app


def main() -> None:
    out = Path(sys.argv[1])
    only = sys.argv[sys.argv.index("--datasets") + 1:] if "--datasets" in sys.argv else None
    client = TestClient(app)
    statuses = {}
    for r in build():
        if only and r["dataset"] not in only:
            continue
        statuses[r["path"]] = client.get(r["path"]).status_code
    tops = {m.split(".")[0] for m in list(sys.modules)}
    pkg_dists = md.packages_distributions()
    used = sorted({d for t in tops for d in pkg_dists.get(t, [])})
    with open("/proc/self/maps") as f:
        maps = sorted({line.split()[-1] for line in f if ".so" in line.split()[-1]})
    site = str(Path(md.distribution("rasterio").locate_file("")))
    out.write_text(json.dumps({
        "ok": sum(1 for s in statuses.values() if s == 200), "n": len(statuses),
        "distributions": used,
        "modules": sorted(m for m in sys.modules if not m.startswith("_")),
        "shared_objects": [m.replace(site + "/", "") for m in maps if m.startswith(site)],
    }, indent=1))
    print(f"{out}: {len(used)} distributions, {sum(1 for s in statuses.values() if s == 200)}/{len(statuses)} ok")


if __name__ == "__main__":
    main()
