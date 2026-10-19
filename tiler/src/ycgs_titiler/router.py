"""Dataset presets: /datasets/{id}/{render}/...

Data requests (tiles, bbox, point, info) are rewritten in place (ASGI scope)
to the backend endpoint that serves the dataset, with the preset's parameters,
the render's band combination and the requested time turned into backend
parameters. titiler then validates and renders them as usual, with no extra
HTTP hop. Metadata (catalog, available times, TileJSON) is served by a normal
FastAPI router.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import timeres
from .presets import (
    CMR_BACKENDS,
    Catalog,
    Dataset,
    DimensionTime,
    GranuleTime,
    Render,
    ScanTime,
    TemplateTime,
    catalog,
)
from .settings import settings

# region data-route
DATA_RE = re.compile(
    r"^/datasets/(?P<id>[^/]+)/(?P<render>[^/]+)/(?P<rest>(?:tiles|bbox|point)/.+|info|info\.geojson)$"
)
TILE_RE = re.compile(r"^tiles/[^/]+/(?P<z>\d+)/\d+/\d+(?:@(?P<scale>\d+)x)?")
BBOX_RE = re.compile(
    r"^bbox/(?P<minx>[-\d.eE]+),(?P<miny>[-\d.eE]+),(?P<maxx>[-\d.eE]+),(?P<maxy>[-\d.eE]+)"
    r"(?:/(?P<w>\d+)x(?P<h>\d+))?"
)
WEB_MERCATOR_Z0_RES = 2 * math.pi * 6378137 / 256
# endregion data-route

# region passthrough
# Parameters a client may add or override (output, warping and color scaling).
PASSTHROUGH = {
    "tilesize", "buffer", "padding", "dst_crs", "coord_crs", "return_mask", "nodata", "reproject",
    "resampling", "max_size", "width", "height", "rescale", "colormap_name", "colormap",
    "color_formula", "algorithm", "algorithm_params", "f",
}  # fmt: skip
PASSTHROUGH_CMR = {"granule_ur", "cloud_cover", "attribute", "pixel_selection", "skipcovered", "items_limit"}
PASSTHROUGH_RAW = {"variables", "assets"}
# Parameters consumed here (never forwarded as is).
TIME_KEYS = {"datetime", "datetime2"}
# endregion passthrough


class PresetError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class Resolved:
    path: str
    params: list[tuple[str, str]]
    pinned: bool  # the response depends only on the URL (cacheable for long)
    time: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    settled: bool = False  # pinned, and the data for that time no longer changes (cacheable for a year)


def lookup(cat: Catalog, ds_id: str, render_name: str | None = None) -> tuple[Dataset, Render | None]:
    if ds_id not in cat.datasets:
        raise PresetError(404, f"unknown dataset {ds_id!r}; see /datasets")
    ds = cat.datasets[ds_id]
    if render_name is None:
        return ds, None
    if render_name not in ds.renders:
        raise PresetError(404, f"unknown render {render_name!r} for {ds_id}; one of {sorted(ds.renders)}")
    return ds, ds.renders[render_name]


# region request-zoom
def request_zoom(rest: str, query: dict[str, list[str]]) -> float | None:
    """Zoom level of a tile, or the Web Mercator zoom equivalent to a bbox request's resolution."""
    if m := TILE_RE.match(rest):
        return int(m["z"]) + math.log2(int(m["scale"] or 1))
    if (m := BBOX_RE.match(rest)) and (m["w"] or "width" in query or "max_size" in query):
        w = float(m["w"] or query.get("width", query.get("max_size", ["1024"]))[0])
        minx, maxx = float(m["minx"]), float(m["maxx"])
        crs = (query.get("coord_crs") or [""])[0].lower()
        projected = "3857" in crs or "900913" in crs or max(abs(minx), abs(maxx)) > 360
        if projected:  # Web Mercator meters
            res = (maxx - minx) / w
        else:  # degrees of longitude: Web Mercator x is 111319.49 m per degree at every latitude
            res = (maxx - minx) * 111319.49079327357 / w
        return math.log2(WEB_MERCATOR_Z0_RES / max(res, 1e-9))
    return None


# endregion request-zoom


def _flatten(params: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for k, v in params.items():
        for item in v if isinstance(v, (list, tuple)) else [v]:
            if item is None:
                continue
            out.append((k, str(item).lower() if isinstance(item, bool) else str(item)))
    return out


# region resolve
def resolve(cat: Catalog, ds_id: str, render_name: str, rest: str, query: dict[str, list[str]]) -> Resolved:
    """Backend path and parameters for a preset data request (blocking: may list S3)."""
    ds, render = lookup(cat, ds_id, render_name)
    assert render is not None
    params: dict[str, Any] = {**ds.params, **ds.zoom_params(request_zoom(rest, query)), **render.params}

    # Time -> backend parameters
    spec = ds.time_for(render)
    dt1 = (query.get("datetime") or [None])[0]
    dt2 = (query.get("datetime2") or [None])[0]
    pinned, resolved_time, headers = True, None, {}
    # When the requested data ends (None: unknown); static data is always settled.
    end: dt.datetime | None = None
    static = False
    try:
        if isinstance(spec, GranuleTime):
            value = dt1 or spec.default
            if value and (dt1 or "granule_ur" not in query):
                granule = timeres.granule_params(spec, value)
                params.update(granule)
                resolved_time = value
                end = timeres.parse_datetime(granule["temporal"].split("/")[-1])
        elif isinstance(spec, TemplateTime):
            url, resolved_time = timeres.template_params(spec, dt1 or spec.default)
            params.update(url)
            end = timeres.step_range(timeres.parse_datetime(resolved_time), spec.step)[1]
        elif isinstance(spec, DimensionTime):
            values = [dt1 or spec.default]
            if render.two_times:
                if not dt2:
                    raise PresetError(400, f"render {render_name!r} needs `datetime2` (compared with `datetime`)")
                values.append(dt2)
            params.update(timeres.dimension_params(spec, values))
            resolved_time = values[0]
            end = max(timeres.parse_datetime(v) for v in values)
        elif isinstance(spec, ScanTime):
            value = dt1 or spec.default
            scan, resolved_time = timeres.scan_params(spec, value)
            params.update(scan)
            pinned = value is not None
            headers["x-ycgs-source"] = scan["url"]
            end = timeres.parse_datetime(resolved_time)
        else:
            static = True
    except timeres.TimeError as e:
        raise PresetError(400 if dt1 or dt2 else 404, str(e)) from e
    settled = pinned and is_settled(ds, end, static)

    allowed = PASSTHROUGH | (PASSTHROUGH_CMR if ds.backend in CMR_BACKENDS else set())
    if render_name == "raw":
        allowed |= PASSTHROUGH_RAW
    for k, v in query.items():
        if k in allowed:
            params[k] = v
        elif k not in TIME_KEYS:
            raise PresetError(
                400, f"query parameter {k!r} is not accepted here; allowed: {sorted(allowed | TIME_KEYS)}"
            )

    if resolved_time:
        headers["x-ycgs-datetime"] = resolved_time
    return Resolved(f"{ds.prefix}/{rest}", _flatten(params), pinned, resolved_time, headers, settled=settled)


def is_settled(ds: Dataset, end: dt.datetime | None, static: bool, now: dt.datetime | None = None) -> bool:
    """Whether data ending at `end` is past the dataset's settling time."""
    if ds.settled_after_days is None:
        return False
    if static:
        return True
    now = now or dt.datetime.now(dt.UTC)
    return end is not None and end < now - dt.timedelta(days=ds.settled_after_days)


# endregion resolve


def _query_dict(query_string: bytes) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for k, v in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True):
        out.setdefault(k, []).append(v)
    return out


# region preset-middleware
class PresetMiddleware:
    """Rewrites /datasets/{id}/{render}/{tiles|bbox|point|info}... to the backend endpoint."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not (m := DATA_RE.match(scope["path"])):
            await self.app(scope, receive, send)
            return
        query = _query_dict(scope.get("query_string", b""))
        try:
            target = await anyio.to_thread.run_sync(resolve, catalog(), m["id"], m["render"], m["rest"], query)
        except PresetError as e:
            await _json_error(send, e.status, e.detail)
            return

        new_scope = dict(scope)
        new_scope["path"] = target.path
        new_scope["raw_path"] = target.path.encode()
        new_scope["query_string"] = urlencode(target.params).encode()
        if target.settled:
            cachecontrol = settings.cachecontrol_settled
        elif target.pinned:
            cachecontrol = settings.cachecontrol_pinned
        else:
            cachecontrol = settings.cachecontrol_latest

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                ok = message["status"] < 400
                headers["cache-control"] = cachecontrol if ok else "no-store"
                for k, v in target.extra_headers.items():
                    headers[k] = v
            await send(message)

        await self.app(new_scope, receive, send_wrapper)


# endregion preset-middleware


async def _json_error(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Metadata endpoints

router = APIRouter()


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _summary(request: Request, ds_id: str, ds: Dataset) -> dict:
    base = _base(request)
    return {
        "id": ds_id,
        "title": ds.title,
        "deployment": ds.deployment,
        "backend": ds.backend,
        "time": ds.time.model_dump(),
        "renders": {k: r.title for k, r in ds.renders.items()},
        "links": {
            "self": f"{base}/datasets/{ds_id}",
            "times": f"{base}/datasets/{ds_id}/times",
            "tilejson": f"{base}/datasets/{ds_id}/{{render}}/WebMercatorQuad/tilejson.json",
            "tiles": f"{base}/datasets/{ds_id}/{{render}}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png",
        },
    }


def _check(ds_id: str, render: str | None = None) -> tuple[Dataset, Render | None]:
    try:
        return lookup(catalog(), ds_id, render)
    except PresetError as e:
        raise HTTPException(e.status, e.detail) from e


@router.get("", summary="List dataset presets")
def list_datasets(request: Request):
    return {k: _summary(request, k, ds) for k, ds in catalog().datasets.items()}


@router.get("/{dataset_id}", summary="Dataset preset")
def get_dataset(request: Request, dataset_id: str):
    ds, _ = _check(dataset_id)
    return {**_summary(request, dataset_id, ds), **ds.model_dump(exclude={"title", "deployment", "backend", "time"})}


@router.get("/{dataset_id}/times", summary="Available times")
def get_times(
    dataset_id: str,
    start: Annotated[str | None, Query(description="ISO date/datetime (UTC); default depends on the dataset")] = None,
    end: Annotated[str | None, Query(description="ISO date/datetime (UTC); default now")] = None,
):
    ds, _ = _check(dataset_id)
    try:
        times = timeres.list_times(catalog(), ds, start, end)
    except timeres.TimeError as e:
        raise HTTPException(400, str(e)) from e
    return {"dataset": dataset_id, "kind": ds.time.kind, "count": len(times), "times": times}


# region latency
def _probe_url(ds: Dataset) -> str:
    """A URL on the host the dataset's data is read from."""
    if ds.backend in CMR_BACKENDS:
        return "https://s3.us-west-2.amazonaws.com/"  # NASA Earthdata Cloud buckets (direct S3 access)
    if isinstance(ds.time, ScanTime):
        return f"https://{ds.time.bucket}.s3.amazonaws.com/"
    if isinstance(ds.time, TemplateTime):
        return ds.time.url
    return ds.params["url"]


@router.get("/{dataset_id}/latency", summary="Connection latency from this deployment to the dataset's data host")
def latency(dataset_id: str, response: Response, n: Annotated[int, Query(ge=1, le=10)] = 3):
    ds, _ = _check(dataset_id)
    url = _probe_url(ds)
    host = urlsplit(url).hostname
    timings = []
    for _ in range(n):
        t0 = time.perf_counter()
        with socket.create_connection((host, 443), timeout=10) as sock:
            t1 = time.perf_counter()
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host):
                t2 = time.perf_counter()
        timings.append({"tcp_ms": round((t1 - t0) * 1000, 1), "tls_ms": round((t2 - t0) * 1000, 1)})
    response.headers["cache-control"] = "no-store"
    return {"dataset": dataset_id, "region": os.environ.get("AWS_REGION"), "host": host, "timings": timings}


# endregion latency


# region tilejson
@router.get("/{dataset_id}/{render}/{tileMatrixSetId}/tilejson.json", summary="TileJSON for a dataset render")
def tilejson(
    request: Request,
    dataset_id: str,
    render: str,
    tileMatrixSetId: str,
    tile_format: Annotated[str, Query(description="Tile format (png, jpeg, webp, tif, npy)")] = "png",
    tile_scale: Annotated[int, Query(ge=1, le=4)] = 1,
):
    ds, r = _check(dataset_id, render)
    assert r is not None
    query = [(k, v) for k, v in request.query_params.multi_items() if k not in ("tile_format", "tile_scale")]
    scale = f"@{tile_scale}x" if tile_scale > 1 else ""
    qs = f"?{urlencode(query)}" if query else ""
    tiles = f"{_base(request)}/datasets/{dataset_id}/{render}/tiles/{tileMatrixSetId}/{{z}}/{{x}}/{{y}}{scale}.{tile_format}{qs}"
    minx, miny, maxx, maxy = ds.bounds
    maxzoom = r.maxzoom or ds.maxzoom
    return {
        "tilejson": "3.0.0",
        "name": f"{dataset_id}/{render}",
        "description": r.title,
        "attribution": ds.attribution,
        "tiles": [tiles],
        "minzoom": ds.minzoom,
        "maxzoom": maxzoom,
        "bounds": [minx, miny, maxx, maxy],
        "center": [(minx + maxx) / 2, (miny + maxy) / 2, ds.minzoom],
    }


# endregion tilejson
