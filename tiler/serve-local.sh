#!/usr/bin/env bash
# Run the tiler locally with real credentials: the Earthdata login from
# ~/.netrc (urs.earthdata.nasa.gov), or the token earthdata_token from the
# repository's _credentials.toml, and the CDS API key from it (cds_api_key). Earthdata granules are read over HTTPS
# (direct S3 access only works inside AWS us-west-2).
#
# Usage: tiler/serve-local.sh [port]   (default 8100)
set -euo pipefail
cd "$(dirname "$0")"
port="${1:-8100}"

eval "$(python3 - <<'EOF'
import shlex, tomllib
from pathlib import Path
out = {}
# Parsed by hand: the netrc module refuses a ~/.netrc others can read.
rc = Path.home() / ".netrc"
words = rc.read_text().split() if rc.exists() else []
for i, w in enumerate(words[:-1]):
    if w == "machine" and words[i + 1] == "urs.earthdata.nasa.gov":
        rest = words[i + 2 :]
        rest = rest[: rest.index("machine")] if "machine" in rest else rest
        entry = dict(zip(rest[::2], rest[1::2]))
        out["TITILER_CMR_EARTHDATA_USERNAME"] = entry.get("login", "")
        out["TITILER_CMR_EARTHDATA_PASSWORD"] = entry.get("password", "")
        break
creds = Path("../_credentials.toml")
toml = tomllib.loads(creds.read_text()) if creds.exists() else {}
if token := toml.get("earthdata_token"):
    out["YCGS_EARTHDATA_TOKEN"] = token
if key := toml.get("cds_api_key"):
    out["YCGS_CDS_API_KEY"] = key
for k, v in out.items():
    print(f"export {k}={shlex.quote(v)}")
EOF
)"

export YCGS_FEATURES=cmr TITILER_CMR_EARTHDATA_S3_DIRECT_ACCESS=FALSE
# GDAL follows the Earthdata login redirect for COGs over HTTPS (HLS) only
# with a cookie jar; ~/.netrc supplies the login.
cookies="$(mktemp -t ycgs-tiler-cookies)"
export GDAL_HTTP_COOKIEFILE="$cookies" GDAL_HTTP_COOKIEJAR="$cookies"
exec uv run uvicorn ycgs_titiler.main:app --port "$port"
