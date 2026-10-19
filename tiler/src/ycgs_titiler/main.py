"""YCGS titiler application.

/datasets  dataset presets (time steps, band combinations), see router.py
/xarray    titiler.xarray for Zarr / NetCDF by URL, with multi-variable bands
/cog       titiler.core for Cloud-Optimized GeoTIFFs by URL (allow-listed hosts)
/cmr       titiler-cmr (NASA CMR granules), when the `cmr` feature is enabled
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, Query
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from titiler.core.dependencies import DefaultDependency
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import ColorMapFactory, TMSFactory
from titiler.core.factory import TilerFactory as CogTilerFactory
from titiler.core.middleware import CacheControlMiddleware
from titiler.xarray.dependencies import SelDimStr
from titiler.xarray.factory import TilerFactory

from . import presets, timeres
from .readers import MissingCredentials, MultiVarReader, URLNotAllowed, check_url
from .router import PresetMiddleware
from .router import router as presets_router
from .settings import settings


# region multivar-params
@dataclass
class MultiVarParams(DefaultDependency):
    """Xarray dataset options: several variables become bands b1..bn."""

    variables: Annotated[list[str], Query(description="Variable names; each becomes a band (b1, b2, ...).")]
    sel: Annotated[
        list[SelDimStr] | None,
        Query(description="Lazy indexing `{dim}={value}` or `{dim}={method}::{value}`, applied before reading."),
    ] = None
    group: Annotated[str | None, Query(description="Zarr / NetCDF group.")] = None
    decode_times: Annotated[bool | None, Query(description="Decode CF times.")] = None
    expression: Annotated[
        str | None,
        Query(description="Band math on b1..bn, `;` between output bands (e.g. `b1;0.45*b1+0.1*b2+0.45*b3;b3`)."),
    ] = None


# endregion multivar-params


# region cog-path
def allowed_cog_url(url: Annotated[str, Query(description="Dataset URL (allow-listed hosts only)")]) -> str:
    check_url(url)
    return url


# endregion cog-path


# region edge-middleware
class EdgeMiddleware:
    """Requests must come through CloudFront (shared secret header), and URLs the
    app builds (TileJSON) use the CloudFront host rather than API Gateway's."""

    def __init__(self, app: ASGIApp, secret: str | None):
        self.app, self.secret = app, secret.encode() if secret else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if self.secret is not None:
            if not hmac.compare_digest(headers.get(b"x-origin-verify", b""), self.secret):
                body = json.dumps({"detail": "Forbidden"}).encode()
                await send(
                    {"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]}
                )
                await send({"type": "http.response.body", "body": body})
                return
            if fwd := headers.get(b"x-ycgs-host"):
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"host"] + [(b"host", fwd)]
                scope["scheme"] = "https"
        await self.app(scope, receive, send)


# endregion edge-middleware


# region create-app
def create_app() -> FastAPI:
    app = FastAPI(
        title="YCGS titiler",
        description=__doc__,
        openapi_url="/api",
        docs_url="/api.html",
    )
    add_exception_handlers(
        app,
        {**DEFAULT_STATUS_CODES, URLNotAllowed: 403, MissingCredentials: 503, KeyError: 404, timeres.TimeError: 400},
    )

    xarray = TilerFactory(
        reader=MultiVarReader,
        reader_dependency=MultiVarParams,
        router_prefix="/xarray",
        add_viewer=True,
    )
    app.include_router(xarray.router, prefix="/xarray", tags=["Xarray (Zarr / NetCDF by URL)"])
    cog = CogTilerFactory(path_dependency=allowed_cog_url, router_prefix="/cog")
    app.include_router(cog.router, prefix="/cog", tags=["Cloud-Optimized GeoTIFF by URL"])
    app.include_router(presets_router, prefix="/datasets", tags=["Dataset presets"])
    app.include_router(TMSFactory().router, tags=["Tiling Schemes"])
    app.include_router(ColorMapFactory().router, tags=["ColorMaps"])

    if "cmr" in settings.feature_set:
        if os.environ.get("TITILER_CMR_EARTHDATA_USERNAME") and os.environ.get("TITILER_CMR_EARTHDATA_PASSWORD"):
            app.mount("/cmr", cmr_app())
        else:
            app.mount(
                "/cmr",
                unavailable(
                    "Earthdata login not configured (set TITILER_CMR_EARTHDATA_USERNAME / _PASSWORD, or the Earthdata secret)"
                ),
            )

    @app.get("/healthz", tags=["Health"])
    def healthz():
        return {"ok": True, "region": os.environ.get("AWS_REGION"), "features": sorted(settings.feature_set)}

    @app.get("/", include_in_schema=False)
    def landing():
        return {
            "title": "YCGS titiler",
            "links": {
                "datasets": "/datasets",
                "api": "/api.html",
                "xarray": "/xarray",
                "cog": "/cog",
                "cmr": "/cmr/api.html",
            },
        }

    # endregion create-app

    # region middleware-order
    # Last added = outermost: Edge -> CORS -> Preset -> CacheControl -> routes.
    # Preset sits inside CORS so its own error responses get CORS headers too,
    # and outside CacheControl so its Cache-Control wins.
    app.add_middleware(CacheControlMiddleware, cachecontrol="public, max-age=3600", exclude_path={r"/healthz"})
    app.add_middleware(PresetMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")], allow_methods=["GET"]
    )
    app.add_middleware(EdgeMiddleware, secret=settings.origin_verify)
    # endregion middleware-order
    return app


# region cmr-app
def unavailable(detail: str) -> ASGIApp:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        body = json.dumps({"detail": detail}).encode()
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return app


def cmr_app() -> FastAPI:
    """titiler-cmr's app, plus an xarray backend for HDF5 groups without coordinates."""
    from titiler.cmr import main as cmr
    from titiler.cmr.dependencies import interpolated_xarray_ds_params
    from titiler.cmr.factory import CMRTilerFactory
    from titiler.core.dependencies import ExpressionParams
    from titiler.xarray.dependencies import DatasetParams as XarrayDatasetParams

    from .readers import GroupedXarrayGranuleReader

    if not getattr(cmr.app.state, "ycgs_grouped", False):
        grouped = CMRTilerFactory(
            router_prefix="/xarray-grouped",
            dataset_reader=GroupedXarrayGranuleReader,
            reader_dependency=interpolated_xarray_ds_params,
            dataset_dependency=XarrayDatasetParams,
            layer_dependency=ExpressionParams,
            add_statistics=True,
            add_viewer=False,
            add_part=True,
            add_ogc_maps=False,
            templates=cmr.templates,
        )
        cmr.app.include_router(grouped.router, prefix="/xarray-grouped", tags=["Xarray Backend (grouped HDF5)"])
        cmr.app.state.ycgs_grouped = True
    # Lambda (Mangum) does not run lifespans; create the CMR client and Earthdata auth now.
    cmr.startup(cmr.app)
    return cmr.app


# endregion cmr-app


# Validate the presets at import (and include them in a SnapStart snapshot).
presets.catalog()
app = create_app()
