"""Turn an installed Lambda package directory into a slim, reproducible zip.

    python slim.py <dir> <out.zip> [--tarball] [--drop pkg ...]

- leaves out packages the Lambda Python runtime already has (boto3, botocore, s3transfer, jmespath)
  and any given with --drop;
- keeps only compiled bytecode: every .py is compiled next to itself (legacy .pyc layout) and the source
  and __pycache__ removed, so imports read one small file each and nothing is compiled at start;
- drops tests, type stubs, C sources and headers;
- writes the zip with sorted entries and fixed timestamps (byte-identical across builds);
- with --tarball, third-party packages go into deps.tar.zst inside the zip (unpacked to /tmp at init by
  ycgs_titiler.lambda_entry): Lambda limits a zip to 250 MB unzipped, and the tiler's libraries are more.
  Only ycgs_titiler/ and lib/ (shared libraries the runtime lacks) stay unpacked.
"""

import compileall
import io
import os
import py_compile
import re
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

RUNTIME = {"boto3", "botocore", "s3transfer", "jmespath"}
EPOCH = (1980, 1, 1, 0, 0, 0)


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


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    drop = set(RUNTIME)
    if "--drop" in sys.argv:
        drop |= set(sys.argv[sys.argv.index("--drop") + 1:])
    tarball = "--tarball" in sys.argv
    drop_packages(root, drop)
    for p in list(root.rglob("*")):
        if p.is_dir() and p.name in ("tests", "test", "__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() and p.suffix in (".pyi", ".pyx", ".pxd", ".c", ".h", ".cpp"):
            p.unlink()
    # Hash-based, unchecked .pyc: no source timestamp inside (reproducible), and no source to check against.
    compileall.compile_dir(str(root), quiet=1, legacy=True, optimize=0, workers=0,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    for p in root.rglob("*.py"):
        if p.with_suffix(".pyc").exists():
            p.unlink()
    files = sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())
    size = sum(p.stat().st_size for p in files)
    entries = [(str(p.relative_to(root)), p) for p in files]
    if tarball:
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
    print(f"{out.name}: {len(files)} files, {size / 2**20:.0f} MB of package, {unzipped / 2**20:.0f} MB unzipped "
          f"(Lambda limit 250), {out.stat().st_size / 2**20:.0f} MB zipped")


if __name__ == "__main__":
    main()
