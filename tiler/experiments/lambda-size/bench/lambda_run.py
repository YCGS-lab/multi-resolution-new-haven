"""Run an unzipped Lambda package in the Lambda Python base image, locally.

The package directory is mounted read-only as /var/task in
public.ecr.aws/lambda/python:3.14, whose Runtime Interface Emulator (RIE) takes
invocations over HTTP. Requests are API Gateway HTTP API (payload v2) events,
as Lambda gets them. Memory and CPU are capped like the Lambda function's
(Lambda gives one vCPU per 1769 MB). Outbound HTTPS goes to the snapshot proxy
on the Docker host.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

import env

IMAGE = os.environ.get("LAMBDA_IMAGE", "public.ecr.aws/lambda/python:3.14")
HANDLER = "ycgs_titiler.lambda_entry.handler"
DOCKER_HOST_IP = os.environ.get("DOCKER_HOST_IP", "172.17.0.1")


def event(path: str) -> dict:
    parts = urlsplit(path)
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": parts.path,
        "rawQueryString": parts.query,
        "headers": {"host": "tiler.local", "accept-encoding": "identity", "user-agent": "bench"},
        "requestContext": {
            "accountId": "000000000000", "apiId": "local", "domainName": "tiler.local", "domainPrefix": "tiler",
            "http": {"method": "GET", "path": parts.path, "protocol": "HTTP/1.1", "sourceIp": "127.0.0.1",
                     "userAgent": "bench"},
            "requestId": "bench", "routeKey": "$default", "stage": "$default",
            "time": "24/Nov/2026:00:00:00 +0000", "timeEpoch": 0,
        },
        "isBase64Encoded": False,
    }


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    seconds: float


class LambdaContainer:
    def __init__(self, task_dir: str, port: int, memory_mb: int = 2048, name: str | None = None,
                 extra_env: dict | None = None, ca_file: str | None = None, limit_mb: int | None = None):
        # memory_mb: the function's memory setting (and so its CPU share); limit_mb: the container's
        # memory cap, if it should differ (headroom where the real setting runs out of memory)
        self.task_dir, self.port, self.memory_mb = task_dir, port, memory_mb
        self.limit_mb = limit_mb or memory_mb
        self.name = name or f"bench-{port}"
        self.extra_env = extra_env or {}
        self.ca_file = ca_file or os.environ["SNAPSHOT_CA"]
        self.started = 0.0

    def start(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)
        proxy = f"http://{DOCKER_HOST_IP}:8899"
        app = env.app_env(dict(os.environ), "/etc/snapshot-ca.pem")
        app.update({"HTTPS_PROXY": proxy, "https_proxy": proxy, "GDAL_HTTP_PROXY": proxy.removeprefix("http://")})
        app.update({"AWS_LAMBDA_FUNCTION_MEMORY_SIZE": str(self.memory_mb), "AWS_LAMBDA_FUNCTION_TIMEOUT": "30",
                    "AWS_LAMBDA_FUNCTION_NAME": self.name, "AWS_REGION": "us-east-1",
                    "AWS_ACCESS_KEY_ID": "bench", "AWS_SECRET_ACCESS_KEY": "bench"})
        app.update(self.extra_env)
        cmd = ["docker", "run", "-d", "--rm", "--name", self.name, "-p", f"127.0.0.1:{self.port}:8080",
               f"--memory={self.limit_mb}m", f"--memory-swap={self.limit_mb}m",
               f"--cpus={max(self.memory_mb / 1769, 0.1):.2f}",
               "-v", f"{os.path.abspath(self.task_dir)}:/var/task:ro",
               "-v", f"{os.path.abspath(self.ca_file)}:/etc/snapshot-ca.pem:ro"]
        for k, v in app.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [IMAGE, HANDLER]
        self.started = time.perf_counter()
        subprocess.run(cmd, check=True, capture_output=True)
        # RIE listens almost at once; init runs on the first invocation.
        for _ in range(200):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=0.2)
            except urllib.error.HTTPError:
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
            else:
                break

    def invoke(self, path: str, timeout: float = 120) -> Response:
        data = json.dumps(event(path)).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/2015-03-31/functions/function/invocations",
                                     data=data, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        dt = time.perf_counter() - t0
        if "statusCode" not in payload:  # unhandled error, init failure
            return Response(599, {}, json.dumps(payload).encode(), dt)
        body = payload.get("body") or ""
        raw = base64.b64decode(body) if payload.get("isBase64Encoded") else body.encode()
        return Response(payload["statusCode"], payload.get("headers") or {}, raw, dt)

    def logs(self) -> str:
        r = subprocess.run(["docker", "logs", self.name], capture_output=True, text=True, check=False)
        return r.stdout + r.stderr

    def init_timings(self) -> dict | None:
        m = re.search(r'\{"ycgs_init": (\{[^}]*\})\}', self.logs())
        return json.loads(m.group(1)) if m else None

    def peak_memory_mb(self) -> float | None:
        """Peak resident memory (VmHWM) of the function's Python process, read on the host: what
        Lambda reports as Max Memory Used, roughly (the container's cgroup also counts page cache)."""
        r = subprocess.run(["docker", "top", self.name, "-eo", "pid,comm"], capture_output=True, text=True, check=False)
        peak = None
        for line in r.stdout.splitlines()[1:]:
            pid, _, comm = line.strip().partition(" ")
            if "python" not in comm:
                continue
            try:
                with open(f"/proc/{pid}/status") as f:
                    for st in f:
                        if st.startswith("VmHWM:"):
                            peak = max(peak or 0, int(st.split()[1]) / 1024)
            except OSError:
                pass
        return peak

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)
