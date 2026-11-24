"""Run the request set through the app in-process, behind the snapshot proxy.

    python record.py OUTDIR [--rounds N]

Used to record the snapshot (proxy in record mode): requests that fail while
the proxy is still downloading an object (5xx) are retried in later rounds
until every request succeeds or stops changing. Responses go to OUTDIR (one
file per request, plus status.json).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import env

env.apply(os.environ)

from fastapi.testclient import TestClient
from requests import build

from ycgs_titiler.main import app


def name(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    rounds = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 30
    reqs = build()
    status: dict[str, dict] = {}
    client = TestClient(app)
    pending = reqs
    for rnd in range(rounds):
        failed = []
        for r in pending:
            t0 = time.perf_counter()
            resp = client.get(r["path"])
            dt = time.perf_counter() - t0
            status[r["path"]] = {"status": resp.status_code, "s": round(dt, 3), "bytes": len(resp.content),
                                 "detail": resp.text[:300] if resp.status_code >= 400 else None}
            if resp.status_code == 200:
                (out / name(r["path"])).write_bytes(resp.content)
            elif resp.status_code >= 500:
                failed.append(r)
            print(f"[{rnd}] {resp.status_code} {dt:6.2f}s {r['path']}", flush=True)
        (out / "status.json").write_text(json.dumps(status, indent=1))
        if not failed:
            break
        print(f"round {rnd}: {len(failed)} failed; waiting for downloads", flush=True)
        pending = failed
        time.sleep(20)


if __name__ == "__main__":
    main()
