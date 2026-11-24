"""Which URLs /xarray and /cog may open, and the errors for URLs and credentials.

Kept apart from readers.py, which imports xarray, zarr and obstore: functions
that serve only Cloud-Optimized GeoTIFFs (YCGS_BACKENDS) need these without them.
"""

import os

# Host whose requests carry the Copernicus CDS API key (ERA5-Land ARCO Zarr).
CDS_ARCO_HOST = "arco.datastores.ecmwf.int"


class URLNotAllowed(ValueError):
    pass


class MissingCredentials(RuntimeError):
    """A data source needs a credential this deployment doesn't have."""


# region allowlist
def allowed_prefixes() -> tuple[str, ...]:
    """URL prefixes /xarray and /cog may open (YCGS_ALLOWED_URL_PREFIXES, comma separated).

    Keeps the endpoint from being used to fetch arbitrary URLs, and keeps the
    CDS key from being sent anywhere but the CDS ARCO host.
    """
    raw = os.environ.get(
        "YCGS_ALLOWED_URL_PREFIXES",
        f"s3://noaa-goes19/,s3://noaa-goes18/,https://{CDS_ARCO_HOST}/,https://data.chc.ucsb.edu/products/CHIRPS/",
    )
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def check_url(url: str) -> None:
    if not any(url.startswith(p) for p in allowed_prefixes()):
        raise URLNotAllowed(f"URL not allowed: {url}")


# endregion allowlist
