"""AWS Lambda entry point (API Gateway HTTP API, payload v2).

Everything expensive happens at import: loading secrets, importing the app,
building the middleware stack and initializing GDAL/PROJ. With SnapStart this
runs once when a version is published and is restored from the snapshot
afterwards; no network connections are opened here other than the AWS SDK's.
"""

import asyncio
import json
import logging
import os


# region load-secrets
def load_secrets() -> None:
    """Export the JSON key/values of the YCGS_SECRET_ARNS secrets as env vars
    (Earthdata login for titiler-cmr, CDS API key for the ERA5-Land ARCO store)."""
    arns = [a.strip() for a in os.environ.get("YCGS_SECRET_ARNS", "").split(",") if a.strip()]
    if not arns:
        return
    import boto3

    client = boto3.client("secretsmanager")
    for arn in arns:
        for key, value in json.loads(client.get_secret_value(SecretId=arn)["SecretString"]).items():
            if value:  # unset values are stored as null
                os.environ[key] = str(value)


load_secrets()
# endregion load-secrets

import pyproj
import rasterio
from mangum import Mangum

from ycgs_titiler import readers, timeres
from ycgs_titiler.main import app

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

logging.getLogger("mangum.lifespan").setLevel(logging.ERROR)
logging.getLogger("mangum.http").setLevel(logging.ERROR)

# region prewarm
# Pre-warm (as titiler-cmr's handler does): middleware stack, GDAL, PROJ database.
app.middleware_stack = app.build_middleware_stack()
_gdal_env = rasterio.Env()
_gdal_env.__enter__()
pyproj.CRS.from_epsg(4326).to_wkt()
pyproj.CRS.from_epsg(3857).to_wkt()

handler = Mangum(app, lifespan="off", text_mime_types=["application/json", "application/geo+json", "text/html"])
# endregion prewarm

# region snapstart-hooks
try:  # SnapStart runtime hooks (Lambda Python 3.12+ base images)
    from snapshot_restore_py import register_after_restore

    @register_after_restore
    def _after_restore():
        # Datasets and listings hold open object-store clients; start fresh.
        readers.clear_caches()
        timeres.clear_caches()
except ImportError:  # pragma: no cover - not running on Lambda
    pass
# endregion snapstart-hooks
