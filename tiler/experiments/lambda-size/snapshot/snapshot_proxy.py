"""mitmproxy addon: record the data the tiler reads, then serve it offline.

    mitmdump -s snapshot_proxy.py --set snapshot_dir=DIR --set snapshot_mode=record|replay \
        --set connection_strategy=lazy -p 8899

Every HTTPS request the tiler makes (CMR searches, Earthdata token, S3 listings,
NetCDF/HDF5/Zarr/COG byte ranges) goes through this proxy (HTTPS_PROXY), which
never connects upstream itself:

- requests with a Range header, and HEADs, are *object* requests: the whole
  object is downloaded once (in record mode, in the background, answering 503
  with Retry-After until it is there) and ranges are served from the local copy.
  Every variant under test then reads the same bytes, whatever ranges it asks for.
- other requests (API calls, listings, small GETs) are *responses*: stored as
  they are, keyed by method, URL and body, and replayed.

In replay mode nothing goes upstream; a miss answers 504 and is logged to
DIR/misses.log. Upstream fetches in record mode use httpx with the environment's
proxy settings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import httpx
from mitmproxy import ctx, http

HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "content-encoding", "content-length"}


def _headers(pairs) -> http.Headers:
    return http.Headers([(str(k).encode(), str(v).encode()) for k, v in pairs])


def _object_key(url: str) -> str:
    # Objects are keyed by scheme, host and path (signed query strings vary).
    base = url.split("?", 1)[0]
    return hashlib.sha256(base.encode()).hexdigest()


def _response_key(method: str, url: str, body: bytes) -> str:
    return hashlib.sha256(method.encode() + b" " + url.encode() + b"\n" + body).hexdigest()


class Snapshot:
    def __init__(self) -> None:
        self.downloads: dict[str, threading.Thread] = {}
        self.failed: dict[str, tuple[float, str]] = {}  # key -> (when, error); retried after 30 s
        self.lock = threading.Lock()

    def load(self, loader) -> None:
        loader.add_option("snapshot_dir", str, "snapshot", "where objects and responses are stored")
        loader.add_option("snapshot_mode", str, "replay", "record or replay")

    # region paths
    @property
    def root(self) -> Path:
        return Path(ctx.options.snapshot_dir)

    def obj_paths(self, key: str) -> tuple[Path, Path]:
        d = self.root / "objects"
        return d / key, d / f"{key}.json"

    def resp_paths(self, key: str) -> tuple[Path, Path]:
        d = self.root / "responses"
        return d / key, d / f"{key}.json"

    # endregion paths

    def log(self, name: str, line: str) -> None:
        with self.lock, open(self.root / name, "a") as f:
            f.write(line + "\n")

    @staticmethod
    def _fwd_headers(flow: http.HTTPFlow) -> dict[str, str]:
        return {k: v for k, v in flow.request.headers.items() if k.lower() not in HOP | {"host", "range"}}

    def _earthdata_token(self) -> str | None:
        """The Earthdata bearer token recorded from the app's own login (URS)."""
        for meta in sorted((self.root / "responses").glob("*.json")):
            m = json.loads(meta.read_text())
            if "find_or_create_token" in m["url"] and m["status"] == 200:
                return json.loads(meta.with_suffix("").read_bytes())["access_token"]
        return None

    # region object-download
    def _download(self, url: str, headers: dict[str, str], key: str) -> None:
        # titiler-cmr's rasterio reader sends no credentials over HTTPS (in production it reads
        # Earthdata Cloud through /vsis3 with in-region S3 credentials). The snapshot is
        # recorded from outside us-west-2, so the proxy adds the app's Earthdata token itself.
        if (url.split("/")[2].endswith("earthdatacloud.nasa.gov")
                and not any(k.lower() == "authorization" for k in headers)
                and (token := self._earthdata_token())):
            headers = {**headers, "Authorization": f"Bearer {token}"}
        data, meta = self.obj_paths(key)
        data.parent.mkdir(parents=True, exist_ok=True)
        tmp = data.with_suffix(".part")
        try:
            t0 = time.time()
            with (httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=600), trust_env=True) as c,
                  c.stream("GET", url, headers=headers) as r):
                if r.status_code >= 400:
                    body = r.read()
                    raise RuntimeError(f"HTTP {r.status_code}: {body[:300]!r}")
                with open(tmp, "wb") as f:
                    f.writelines(r.iter_bytes(1 << 20))
                keep = {k: v for k, v in r.headers.items()
                        if k.lower() in ("content-type", "etag", "last-modified", "x-amz-meta-mtime")}
            tmp.rename(data)
            meta.write_text(json.dumps({"url": url, "headers": keep, "size": data.stat().st_size}))
            self.log("objects.log", f"{data.stat().st_size}\t{time.time() - t0:.1f}s\t{url}")
        except Exception as e:  # noqa: BLE001
            self.failed[key] = (time.time(), str(e))
            self.log("errors.log", f"object {url}: {e} (headers: {sorted(k for k in headers)})")
        finally:
            with self.lock:
                self.downloads.pop(key, None)

    # endregion object-download

    def _serve_object(self, flow: http.HTTPFlow, key: str) -> None:
        data, meta = self.obj_paths(key)
        info = json.loads(meta.read_text())
        size = info["size"]
        headers = {**info["headers"], "Accept-Ranges": "bytes"}
        if flow.request.method == "HEAD":
            flow.response = http.Response.make(200, b"", headers)
            # make() sets Content-Length from the (empty) body; a HEAD gives the object's size.
            flow.response.headers["content-length"] = str(size)
            return
        rng = flow.request.headers.get("range", "")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m:
            flow.response = http.Response.make(200, data.read_bytes(), headers)
            return
        a, b = m.groups()
        if a == "":  # suffix range
            start, end = max(0, size - int(b)), size - 1
        else:
            start, end = int(a), min(int(b) if b else size - 1, size - 1)
        if start >= size:
            flow.response = http.Response.make(416, b"", {"Content-Range": f"bytes */{size}"})
            return
        with open(data, "rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        flow.response = http.Response.make(206, body, {**headers, "Content-Range": f"bytes {start}-{end}/{size}"})

    # region request-hook
    async def request(self, flow: http.HTTPFlow) -> None:
        req = flow.request
        url = req.pretty_url
        record = ctx.options.snapshot_mode == "record"
        self.log("requests.log", f"{req.method}\t{req.headers.get('range', '')}\t{url}")
        if req.method in ("GET", "HEAD") and (req.method == "HEAD" or "range" in req.headers):
            key = _object_key(url)
            data, meta = self.obj_paths(key)
            if meta.exists():
                self._serve_object(flow, key)
                return
            if not record:
                self.log("misses.log", f"object\t{url}")
                flow.response = http.Response.make(504, b"snapshot miss", {})
                return
            if key in self.failed:
                when, err = self.failed[key]
                if time.time() - when < 30:
                    flow.response = http.Response.make(502, err.encode(), {})
                    return
                del self.failed[key]
            with self.lock:
                if key not in self.downloads:
                    t = threading.Thread(target=self._download, args=(url, self._fwd_headers(flow), key), daemon=True)
                    self.downloads[key] = t
                    t.start()
            # Wait a little (small objects finish quickly), then ask the client to retry.
            for _ in range(100):
                await asyncio.sleep(0.1)
                if meta.exists():
                    self._serve_object(flow, key)
                    return
            flow.response = http.Response.make(503, b"downloading", {"Retry-After": "5"})
            return

        body = req.raw_content or b""
        # CMR pages through results with a header, not the URL.
        page = req.headers.get("cmr-search-after")
        key = _response_key(req.method, url + (f"#cmr-search-after={page}" if page else ""), body)
        data, meta = self.resp_paths(key)
        if meta.exists():
            m = json.loads(meta.read_text())
            flow.response = http.Response.make(m["status"], data.read_bytes(), _headers(m["headers"]))
            return
        if not record:
            self.log("misses.log", f"response\t{req.method}\t{url}")
            flow.response = http.Response.make(504, b"snapshot miss", {})
            return

        def fetch():
            with httpx.Client(follow_redirects=True, timeout=120, trust_env=True) as c:
                return c.request(req.method, url, headers=self._fwd_headers(flow), content=body)

        try:
            r = await asyncio.to_thread(fetch)
        except Exception as e:  # noqa: BLE001
            self.log("errors.log", f"response {req.method} {url}: {e}")
            flow.response = http.Response.make(502, str(e).encode(), {})
            return
        headers = [(k, v) for k, v in r.headers.multi_items() if k.lower() not in HOP]
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_bytes(r.content)
        meta.write_text(json.dumps({"url": url, "method": req.method, "status": r.status_code, "headers": headers}))
        self.log("responses.log", f"{r.status_code}\t{len(r.content)}\t{req.method}\t{url}")
        flow.response = http.Response.make(r.status_code, r.content, _headers(headers))

    # endregion request-hook


addons = [Snapshot()]
