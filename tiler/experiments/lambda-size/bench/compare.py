"""Compare a variant's responses with the baseline's (P0), request by request.

    python compare.py RESULTS_DIR BASELINE VARIANT [VARIANT ...]

.npy (raw renders: data bands plus the mask as the last band): identical
arrays, the largest absolute difference in the data bands, and the share of
pixels whose mask differs. PNG: the decoded pixels (RGBA), identical or the
share of pixels that differ. Writes RESULTS_DIR/<variant>/compare.json.
"""

from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from requests import build
from run import out_name


def load(path: Path, ext: str) -> np.ndarray:
    raw = path.read_bytes()
    if ext == "npy":
        return np.load(io.BytesIO(raw))
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))


def compare(a: np.ndarray, b: np.ndarray, ext: str) -> dict:
    if a.shape != b.shape:
        return {"identical": False, "shape": [a.shape, b.shape]}
    if ext == "npy":
        da, db = a[:-1].astype("float64"), b[:-1].astype("float64")
        same = np.array_equal(a, b, equal_nan=True)
        diff = np.abs(da - db)
        valid = ~(np.isnan(da) & np.isnan(db))
        return {"identical": bool(same),
                "max_abs_diff": float(np.nanmax(np.where(valid, diff, 0))) if diff.size else 0.0,
                "mask_differs": float(np.mean(a[-1] != b[-1]))}
    differ = np.any(a != b, axis=-1)
    return {"identical": bool(not differ.any()), "pixels_differ": float(differ.mean()),
            "max_channel_diff": int(np.abs(a.astype(int) - b.astype(int)).max())}


def main() -> None:
    root, base, variants = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
    reqs = build()
    for v in variants:
        rows, summary = [], defaultdict(lambda: defaultdict(int))
        for r in reqs:
            ext = r["path"].split("?")[0].rsplit(".", 1)[1]
            pa, pb = root / base / "responses" / out_name(r["path"]), root / v / "responses" / out_name(r["path"])
            s = summary[r["dataset"]]
            if not pa.exists() or not pb.exists():
                row = {"missing": [str(p.parent.parent.name) for p in (pa, pb) if not p.exists()]}
                s["missing"] += 1
            else:
                row = compare(load(pa, ext), load(pb, ext), ext)
                s["identical" if row["identical"] else "different"] += 1
                if not row["identical"] and "max_abs_diff" in row:
                    s["max_abs_diff"] = max(s["max_abs_diff"], row["max_abs_diff"])
            rows.append({"path": r["path"], "dataset": r["dataset"], **row})
        out = {"baseline": base, "variant": v, "by_dataset": {k: dict(x) for k, x in summary.items()}, "rows": rows}
        (root / v / "compare.json").write_text(json.dumps(out, indent=1))
        tot = defaultdict(int)
        for x in summary.values():
            for k in ("identical", "different", "missing"):
                tot[k] += x.get(k, 0)
        print(f"{v} vs {base}: {dict(tot)}")
        for ds, x in summary.items():
            if x.get("different") or x.get("missing"):
                print(f"   {ds}: {dict(x)}")


if __name__ == "__main__":
    main()
