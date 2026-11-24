"""Environment of the tiler under test: all features in one app, all HTTPS
through the snapshot proxy, credentials from this machine's environment."""

import os

PROXY = os.environ.get("SNAPSHOT_PROXY", "http://127.0.0.1:8899")


# The regional-api module's GDAL settings (terraform/tiler/modules/regional-api/main.tf, gdal_env).
GDAL_ENV = {
    "GDAL_CACHEMAX": "200",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_INGESTED_BYTES_AT_OPEN": "32768",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "5000000",
    "PYTHONWARNINGS": "ignore",
    "AWS_EC2_METADATA_DISABLED": "true",
}


def app_env(source: dict, ca_file: str) -> dict[str, str]:
    """Variables to give the app (in-process or in a Lambda container)."""
    return {
        **GDAL_ENV,
        "YCGS_FEATURES": "cmr",
        "TITILER_CMR_EARTHDATA_USERNAME": source.get("EARTHDATA_LOGIN_USER", ""),
        "TITILER_CMR_EARTHDATA_PASSWORD": source.get("EARTHDATA_LOGIN_PASSWORD", ""),
        # outside us-west-2: HTTPS downloads instead of direct S3 (same for every variant)
        "TITILER_CMR_EARTHDATA_S3_DIRECT_ACCESS": "FALSE",
        "YCGS_CDS_API_KEY": source.get("CDSAPI_KEY", ""),
        "HTTPS_PROXY": PROXY,
        "https_proxy": PROXY,
        "NO_PROXY": "localhost,127.0.0.1",
        "SSL_CERT_FILE": ca_file,
        "REQUESTS_CA_BUNDLE": ca_file,
        "CURL_CA_BUNDLE": ca_file,
        "GDAL_CURL_CA_BUNDLE": ca_file,  # rasterio otherwise sets it to certifi's bundle
        "AWS_CA_BUNDLE": ca_file,
        "GDAL_HTTP_PROXY": PROXY.removeprefix("http://"),
        "AWS_REGION": "us-east-1",
        "AWS_NO_SIGN_REQUEST": "YES",
    }


def apply(environ) -> None:
    ca = environ.get("SNAPSHOT_CA", "")
    for k, v in app_env(dict(environ), ca).items():
        environ[k] = v
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        environ.pop(k, None)
