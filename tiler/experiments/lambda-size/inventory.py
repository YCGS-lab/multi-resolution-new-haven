"""Size inventory of an unpacked Lambda package directory.

    python inventory.py <dir> [--json out.json]

Prints MB per top-level entry (packages, .libs dirs), and every shared library
grouped by library name (soname without the auditwheel hash), so copies of the
same native library bundled by several wheels show up together.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def tree_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def lib_name(name: str) -> str:
    # libproj-00dfde79.so.25.9.8.1 -> libproj ; libgdal.so.38 -> libgdal
    base = name.split(".so")[0]
    return re.sub(r"-[0-9a-f]{8}$", "", base)


def main() -> None:
    root = Path(sys.argv[1])
    total = tree_size(root)
    tops = sorted(((tree_size(p), p.name) for p in root.iterdir()), reverse=True)
    libs = defaultdict(list)
    for f in root.rglob("*.so*"):
        if (f.is_file() and ".so" in f.name and not f.name.endswith((".py", ".pyc"))
                and (f.parent.name.endswith(".libs") or f.parent.name == "lib")):
            libs[lib_name(f.name)].append((f.stat().st_size, str(f.relative_to(root))))
    ext = sum(f.stat().st_size for f in root.rglob("*.so") if f.is_file() and "cpython" in f.name or ".abi3." in f.name)
    print(f"total {total / 2**20:.1f} MB ({sum(1 for _ in root.rglob('*'))} entries); extension modules {ext / 2**20:.1f} MB")
    print("\n## top-level entries >= 0.5 MB")
    for s, n in tops:
        if s >= 0.5 * 2**20:
            print(f"{s / 2**20:7.1f}  {n}")
    print("\n## bundled shared libraries (duplicates marked *)")
    rows = sorted(libs.items(), key=lambda kv: -sum(s for s, _ in kv[1]))
    for name, copies in rows:
        mark = "*" if len(copies) > 1 else " "
        for s, path in copies:
            print(f"{mark} {s / 2**20:6.1f}  {name:20s} {path}")
    dup = sum(sum(s for s, _ in c) - max(s for s, _ in c) for c in libs.values() if len(c) > 1)
    print(f"\nduplicate copies: {dup / 2**20:.1f} MB")
    if "--json" in sys.argv:
        out = {"total_mb": total / 2**20, "top": {n: s / 2**20 for s, n in tops},
               "libs": {k: [(s / 2**20, p) for s, p in v] for k, v in libs.items()}, "duplicate_mb": dup / 2**20}
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
