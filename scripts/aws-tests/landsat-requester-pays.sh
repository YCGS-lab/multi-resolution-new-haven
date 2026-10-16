#!/usr/bin/env bash
# The one pipeline step that reads AWS with credentials: the Landsat Level-1
# panchromatic window from the requester-pays bucket s3://usgs-landsat
# (scripts/landsat/download.py, with the aws_* keys in _credentials.toml).
# Creates no AWS resources; the read costs a few cents at most.
#
# Re-runs the download (it rewrites the same window) and checks the result is
# identical to the file already in data/landsat/, if there is one.
source "$(dirname "$0")/lib.sh"

cd "$REPO"
[[ -f data/landsat/scene.json ]] || die "no data/landsat/scene.json (run scripts/landsat/select_scene.py)"
[[ -f _credentials.toml ]] || die "no _credentials.toml with aws_access_key_id / aws_secret_access_key"

pan="$(ls data/landsat/*_B8_newhaven.tif 2>/dev/null | head -1 || true)"
before=""
if [[ -n "$pan" ]]; then
  before="$(uv run -q --with rasterio python -c "import rasterio,hashlib,sys; print(hashlib.sha256(rasterio.open(sys.argv[1]).read().tobytes()).hexdigest())" "$pan")"
fi

log "scripts/landsat/download.py (requester-pays read with the _credentials.toml keys)"
uv run -q scripts/landsat/download.py

pan="$(ls data/landsat/*_B8_newhaven.tif | head -1)"
after="$(uv run -q --with rasterio python -c "import rasterio,hashlib,sys; print(hashlib.sha256(rasterio.open(sys.argv[1]).read().tobytes()).hexdigest())" "$pan")"
if [[ -n "$before" && "$before" != "$after" ]]; then
  die "pixels differ from the previous download"
fi
log "ok: $pan${before:+ (pixels identical to the previous download)}"
