"""Lambda entry point of the zip package (managed Python runtime, no container image).

The tiler's third-party packages are more than a Lambda zip may hold unpacked
(250 MB), so they ship as deps.tar.zst inside the zip (package/slim.py) and are
unpacked to /tmp here, once per execution environment, before the app is
imported. Imports then read local disk. Timings go to the log as one JSON line.
"""

import json
import os
import sys
import tarfile
import time

_t0 = time.perf_counter()
_ROOT = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEPS = os.path.join(_ROOT, "deps.tar.zst")
_TARGET = os.environ.get("YCGS_DEPS_DIR", "/tmp/deps")


def _unpack() -> bool:
    if os.path.exists(os.path.join(_TARGET, ".complete")):
        return False
    tmp = f"{_TARGET}.{os.getpid()}"
    with tarfile.open(_DEPS, "r:zst") as t:
        t.extractall(tmp, filter="data")
    open(os.path.join(tmp, ".complete"), "w").close()
    os.replace(tmp, _TARGET) if not os.path.exists(_TARGET) else None
    return True


_unpacked = _unpack() if os.path.exists(_DEPS) else False
sys.path.insert(0, _TARGET)
_t1 = time.perf_counter()

from ycgs_titiler.handler import handler  # noqa: F401

print(json.dumps({"ycgs_init": {"unpack_s": round(_t1 - _t0, 3), "unpacked": _unpacked,
                                "import_s": round(time.perf_counter() - _t1, 3)}}), flush=True)


def prune(event, context):
    """The lookup cache's weekly prune job (same package, different handler)."""
    from ycgs_titiler.prune import handler as prune_handler

    return prune_handler(event, context)
