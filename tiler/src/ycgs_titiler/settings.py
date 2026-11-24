"""Settings (environment variables prefixed YCGS_)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


# region settings
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YCGS_", extra="ignore")

    # Optional features: "cmr" mounts titiler-cmr at /cmr (needs Earthdata credentials).
    features: str = ""
    # Shared secret CloudFront sends as X-Origin-Verify; requests without it are
    # rejected (unset: no check, e.g. local runs).
    origin_verify: str | None = None
    cors_origins: str = "*"
    # Cache-Control for preset responses whose time is fixed by the URL and whose
    # data is settled (a year in CloudFront, s-maxage; a day in browsers, which
    # can't be purged), whose time is fixed but recent, and for "latest"
    # requests (no datetime).
    cachecontrol_settled: str = "public, max-age=86400, s-maxage=31536000"
    cachecontrol_pinned: str = "public, max-age=86400"
    cachecontrol_latest: str = "public, max-age=60"
    # Backends this function serves (datasets.yaml `backend`, comma separated; empty: all).
    # Endpoints and readers of the others are neither mounted nor imported, so a
    # function's package can leave out their libraries (one function per reader
    # type; see docs/tiler/lambda.md).
    backends: str = ""
    # Comma-separated Secrets Manager ARNs whose JSON key/values become env vars at cold start.
    secret_arns: str = ""

    @property
    def feature_set(self) -> set[str]:
        return {f.strip() for f in self.features.split(",") if f.strip()}

    @property
    def backend_set(self) -> set[str]:
        """The backends this function serves (all when YCGS_BACKENDS is unset)."""
        from .presets import BACKEND_PREFIX

        return {b.strip() for b in self.backends.split(",") if b.strip()} or set(BACKEND_PREFIX)


# endregion settings


settings = Settings()
