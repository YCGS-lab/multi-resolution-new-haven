# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Serve the repository root over HTTP, with Range requests (needed by the
website to read parts of the Cloud-Optimized GeoTIFFs in website/image-data/;
Python's built-in `http.server` ignores Range and would send whole files).

    uv run scripts/website/serve.py [--port 8000]
    # open http://localhost:8000/website/
"""

import argparse
import os
import re
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus single-range `Range: bytes=a-b` support."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".tif": "image/tiff",
        ".js": "text/javascript",
        ".wasm": "application/wasm",
    }

    def send_head(self):
        self._range = None
        m = RANGE.match(self.headers.get("Range", "").strip())
        path = self.translate_path(self.path)
        if not m or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        a, b = m.groups()
        if a:
            start, end = int(a), min(int(b) if b else size - 1, size - 1)
        else:  # suffix range: last N bytes
            start, end = max(size - int(b or 0), 0), size - 1
        if start >= size or start > end:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self._range = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._range))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if self._range is None:
            return super().copyfile(source, outputfile)
        left = self._range
        while left > 0:
            chunk = source.read(min(left, 1 << 20))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)

    def end_headers(self):
        if getattr(self, "_range", None) is None:  # (range responses already have it)
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--verbose", action="store_true", help="log every request")
    args = p.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), partial(RangeHandler, directory=str(REPO)))
    print(f"serving {REPO} at http://{args.bind}:{args.port}/website/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
