"""Keep one copy of each native library that several wheels bundle (variant V2).

    python dedupe.py <site-packages dir> [--prefer rasterio.libs]

auditwheel gives every wheel its own copy of the libraries it links
(libproj-<hash>.so.25.9.8.1 in both rasterio.libs and pyproj.libs). Copies with
the same library name and the same full version, where the copy that stays
exports every symbol of the one that goes, are treated as the same library
(rasterio's PROJ renames its symbols, so it is *not* pyproj's): every ELF file
that needs a copy that goes is re-pointed
(`patchelf --replace-needed`, plus a RUNPATH entry relative to $ORIGIN) at the
copy that stays (in --prefer's directory when it has one). Libraries in *.libs
that nothing needs any more are then removed, repeatedly.

Different versions of a library are left alone (HDF5 2.0.0 in h5py vs 2.2.0 in
rasterio: HDF5 checks the version at run time).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ELF = b"\x7fELF"


def is_elf(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(4) == ELF
    except OSError:
        return False


def needed(p: Path) -> list[str]:
    out = subprocess.run(["patchelf", "--print-needed", str(p)], capture_output=True, text=True, check=True)
    return out.stdout.split()


def runpath(p: Path) -> list[str]:
    out = subprocess.run(["patchelf", "--print-rpath", str(p)], capture_output=True, text=True, check=True)
    return [r for r in out.stdout.strip().split(":") if r]


def exported(p: Path) -> set[str]:
    out = subprocess.run(["nm", "-D", "--defined-only", str(p)], capture_output=True, text=True, check=True).stdout
    return {line.split()[-1] for line in out.splitlines() if line.strip()}


def identity(name: str) -> tuple[str, str] | None:
    # libproj-00dfde79.so.25.9.8.1 -> ("libproj", "25.9.8.1")
    m = re.fullmatch(r"(lib[\w+.-]*?)-[0-9a-f]{8}\.so\.([\d.]+)", name)
    return (m.group(1), m.group(2)) if m else None


def main() -> None:
    root = Path(sys.argv[1])
    prefer = sys.argv[sys.argv.index("--prefer") + 1] if "--prefer" in sys.argv else "rasterio.libs"
    libs = [p for d in root.glob("*.libs") for p in d.iterdir() if p.is_file() and is_elf(p)]
    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for p in libs:
        if (ident := identity(p.name)) is not None:
            groups[ident].append(p)
    replace: dict[str, Path] = {}  # file name of a copy that goes -> the copy that stays
    for ident, copies in sorted(groups.items()):
        if len(copies) < 2:
            continue
        keep = next((c for c in copies if c.parent.name == prefer), min(copies))
        keep_syms = exported(keep)
        for c in copies:
            if c == keep:
                continue
            # Same version is not enough: rasterio's wheel renames PROJ's symbols (internal_proj_*)
            # so that it can't clash with pyproj's copy.
            if missing := exported(c) - keep_syms:
                print(f"{ident[0]} {ident[1]}: {c.relative_to(root)} kept ({len(missing)} symbols not in "
                      f"{keep.relative_to(root)}, e.g. {min(missing)})")
                continue
            replace[c.name] = keep
            print(f"{ident[0]} {ident[1]}: {c.relative_to(root)} -> {keep.relative_to(root)}")
    elves = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink() and ".so" in p.name and is_elf(p)]
    wanted_before = {n for f in elves for n in needed(f)}
    for f in elves:
        swaps = [(n, replace[n]) for n in needed(f) if n in replace]
        if not swaps:
            continue
        rp = runpath(f)
        for old, keep in swaps:
            subprocess.run(["patchelf", "--replace-needed", old, keep.name, str(f)], check=True)
            entry = "$ORIGIN/" + os.path.relpath(keep.parent, f.parent)
            if entry not in rp:
                rp.append(entry)
        subprocess.run(["patchelf", "--set-rpath", ":".join(rp), str(f)], check=True)
    for name, keep in replace.items():
        for c in groups[identity(name)]:
            if c.name == name and c.exists():
                c.unlink()
    # Remove libraries nothing needs any more (e.g. pyproj's sqlite and curl, needed only by its libproj).
    while True:
        elves = [p for p in root.rglob("*") if p.is_file() and ".so" in p.name and is_elf(p)]
        wanted = {n for f in elves for n in needed(f)}
        # only libraries something linked before (not ones loaded with dlopen)
        orphans = [p for d in root.glob("*.libs") for p in d.iterdir()
                   if p.is_file() and p.name in wanted_before and p.name not in wanted]
        if not orphans:
            break
        for p in orphans:
            print(f"unused: {p.relative_to(root)}")
            p.unlink()


if __name__ == "__main__":
    main()
