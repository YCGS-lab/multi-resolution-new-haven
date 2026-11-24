"""Distributions in a package directory that a trace (trace.py) never imported, by size.

    python unused.py TRACE.json SITE_DIR
"""

import json
import os
import re
import sys
from pathlib import Path


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "_", n).lower()


def main() -> None:
    with open(sys.argv[1]) as f:
        t = json.load(f)
    site = sys.argv[2]
    used = {norm(d) for d in t["distributions"]}
    rows = []
    for d in os.listdir(site):
        if not d.endswith(".dist-info"):
            continue
        rec = os.path.join(site, d, "RECORD")
        lines = Path(rec).read_text().splitlines() if os.path.exists(rec) else []
        paths = [os.path.join(site, ln.split(",")[0]) for ln in lines if ln]
        size = sum(os.path.getsize(p) for p in paths if os.path.isfile(p))
        tops = sorted({ln.split(",")[0].split("/")[0] for ln in lines if ln and not ln.startswith(d)})
        name = norm(d.split("-")[0])
        if name not in used:
            rows.append((size, name, tops))
    for size, name, tops in sorted(rows, reverse=True):
        print(f"{size / 2**20:6.2f}  {name:24s} {' '.join(tops)}")
    print(f"never imported: {sum(r[0] for r in rows) / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
