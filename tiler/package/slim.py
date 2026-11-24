"""Turn an installed Lambda package directory into a slim, reproducible zip.

    python slim.py <dir> <out.zip> [--strip] [--share-proj-data] [--trim trim.txt] [--drop pkg ...]
                   [--drop-paths glob ...] [--tarball] [--max-mb 250]
    python slim.py <dir> --strip-only

- leaves out packages the Lambda Python runtime already has (boto3, botocore, s3transfer, jmespath)
  and any given with --drop;
- keeps only compiled bytecode: every .py is compiled next to itself (legacy .pyc layout) and the source
  and __pycache__ removed, so imports read one small file each and nothing is compiled at start;
- drops tests, type stubs, C sources and headers, and any --drop-paths (globs relative to <dir>);
- with --trim, also the packages and paths listed in that file (package/trim.txt: what the tiler
  never loads);
- with --strip, removes symbols not needed for dynamic linking from every shared object
  (`strip --strip-unneeded`): most wheels ship their extension modules and bundled libraries with
  debug symbols, about a fifth of the tiler's package;
- with --share-proj-data, drops rasterio's copy of the PROJ data (the same proj.db as pyproj's, for
  the same PROJ version); ycgs_titiler.lambda_entry points PROJ_DATA at pyproj's;
- writes the zip with sorted entries and fixed timestamps (byte-identical across builds);
- with --tarball, third-party packages go into deps.tar.zst inside the zip (unpacked to /tmp at init by
  ycgs_titiler.lambda_entry). Only ycgs_titiler/ and lib/ (shared libraries the runtime lacks) stay
  unpacked. Without it, the build fails if the zip is over --max-mb unzipped (Lambda's limit: 250 MB).
"""

import argparse
import compileall
import io
import os
import py_compile
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

RUNTIME = {"boto3", "botocore", "s3transfer", "jmespath"}
EPOCH = (1980, 1, 1, 0, 0, 0)
ELF = b"\x7fELF"


def dist_name(d: str) -> str:
    return re.sub(r"[-_.]+", "_", d.split("-")[0]).lower()


def drop_packages(root: Path, names: set[str]) -> None:
    names = {re.sub(r"[-_.]+", "_", n).lower() for n in names}
    for info in root.glob("*.dist-info"):
        if dist_name(info.name) not in names:
            continue
        record = (info / "RECORD").read_text().splitlines() if (info / "RECORD").exists() else []
        tops = {line.split(",")[0].split("/")[0] for line in record if line}
        for t in tops:
            p = root / t
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()


def remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def loadable(path: Path) -> bool:
    """Every LOAD segment's file offset and address agree modulo its alignment (the loader
    refuses the file otherwise: "ELF load command address/offset not page-aligned")."""
    out = subprocess.run(["readelf", "-lW", str(path)], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "LOAD":
            offset, vaddr, align = int(f[1], 16), int(f[2], 16), int(f[-1], 16)
            if align > 1 and offset % align != vaddr % align:
                return False
    return True


def strip_shared_objects(root: Path) -> None:
    """strip --strip-unneeded every shared object, keeping the original where stripping breaks
    it (binutils' strip can misplace the segments of libraries auditwheel already patched, e.g.
    numpy's bundled OpenBLAS)."""
    kept = []
    for p in sorted(root.rglob("*.so*")):
        if not p.is_file() or p.is_symlink():
            continue
        with open(p, "rb") as f:
            if f.read(4) != ELF:
                continue
        tmp = p.with_name(p.name + ".stripped")
        subprocess.run(["strip", "--strip-unneeded", "-o", str(tmp), str(p)], check=True)
        if loadable(tmp):
            shutil.copymode(p, tmp)
            tmp.replace(p)
        else:
            tmp.unlink()
            kept.append(str(p.relative_to(root)))
    if kept:
        print(f"not stripped (stripping would break them): {' '.join(kept)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--strip-only", action="store_true", help="only strip the shared objects in <dir>")
    ap.add_argument("--tarball", action="store_true")
    ap.add_argument("--strip", action="store_true")
    ap.add_argument("--share-proj-data", action="store_true")
    ap.add_argument("--drop", nargs="*", default=[])
    ap.add_argument("--drop-paths", nargs="*", default=[])
    ap.add_argument("--trim", type=Path, help="file of `package NAME` / `path GLOB` lines to leave out")
    ap.add_argument("--max-mb", type=float, default=250)
    args = ap.parse_args()
    root, out = args.root, args.out
    if args.strip_only:
        strip_shared_objects(root)
        return

    if args.trim:
        for line in args.trim.read_text().splitlines():
            kind, _, value = line.split("#", 1)[0].strip().partition(" ")
            if kind == "package":
                args.drop.append(value.strip())
            elif kind == "path":
                args.drop_paths.append(value.strip())
            elif kind:
                raise SystemExit(f"{args.trim}: unknown line {line!r}")
    drop_packages(root, RUNTIME | set(args.drop))
    for p in list(root.rglob("*")):
        if p.is_dir() and p.name in ("tests", "test", "__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() and p.suffix in (".pyi", ".pyx", ".pxd", ".c", ".h", ".cpp"):
            p.unlink()
    for pattern in args.drop_paths:
        for p in sorted(root.glob(pattern), reverse=True):
            remove(p)
    if args.share_proj_data and (root / "pyproj/proj_dir/share/proj/proj.db").exists():
        remove(root / "rasterio/proj_data")
    if args.strip:
        strip_shared_objects(root)
    # Hash-based, unchecked .pyc: no source timestamp inside (reproducible), and no source to check against.
    compileall.compile_dir(str(root), quiet=1, legacy=True, optimize=0, workers=0,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    for p in root.rglob("*.py"):
        if p.with_suffix(".pyc").exists():
            p.unlink()
    files = sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())
    size = sum(p.stat().st_size for p in files)
    entries = [(str(p.relative_to(root)), p) for p in files]
    if args.tarball:
        keep = ("ycgs_titiler/", "lib/")
        packed = [(n, p) for n, p in entries if not n.startswith(keep)]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:zst", level=10) as t:
            for n, p in packed:
                ti = tarfile.TarInfo(n)
                ti.size, ti.mtime, ti.mode = p.stat().st_size, 0, 0o755 if os.access(p, os.X_OK) else 0o644
                t.addfile(ti, io.BytesIO(p.read_bytes()))
        print(f"deps.tar.zst: {len(packed)} files, {sum(p.stat().st_size for _, p in packed) / 2**20:.0f} MB -> "
              f"{len(buf.getvalue()) / 2**20:.0f} MB")
        entries = [(n, p) for n, p in entries if n.startswith(keep)] + [("deps.tar.zst", buf.getvalue())]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, p in sorted(entries, key=lambda e: e[0]):
            info = zipfile.ZipInfo(n, EPOCH)
            data = p if isinstance(p, bytes) else p.read_bytes()
            exe = not isinstance(p, bytes) and os.access(p, os.X_OK)
            info.external_attr = (0o755 if exe else 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED if isinstance(p, bytes) else zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(out) as z:
        unzipped = sum(i.file_size for i in z.infolist())
    print(f"{out.name}: {len(files)} files, {size / 2**20:.1f} MB of package, {unzipped / 2**20:.1f} MB unzipped "
          f"(Lambda limit 250), {out.stat().st_size / 2**20:.1f} MB zipped")
    if not args.tarball and unzipped > args.max_mb * 2**20:
        raise SystemExit(f"{out.name} is {unzipped / 2**20:.1f} MB unzipped, over {args.max_mb:g} MB")


if __name__ == "__main__":
    main()
