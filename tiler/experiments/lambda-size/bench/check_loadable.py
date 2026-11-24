"""Load every shared object of an unpacked package (run inside the Lambda image):
    python check_loadable.py /var/task
Fails if any can't be loaded for a reason other than a missing symbol from Python itself."""

import ctypes
import glob
import os
import sys

root = sys.argv[1]
bad = []
for p in sorted(glob.glob(f"{root}/**/*.so*", recursive=True)):
    try:
        ctypes.CDLL(p)
    except OSError as e:
        bad.append(f"{os.path.relpath(p, root)}: {str(e)[-120:]}")
print(f"{root}: {len(bad)} of the shared objects failed to load")
for b in bad:
    print("  " + b)
sys.exit(1 if bad else 0)
