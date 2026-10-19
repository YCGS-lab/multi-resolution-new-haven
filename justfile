# Download data/ for every dataset (picking the Landsat scene and NISAR granule if not yet picked)
download:
  [ -f data/landsat/scene.json ] || uv run scripts/landsat/select_scene.py
  [ -f data/nisar-gcov/granule.json ] || uv run scripts/nisar-gcov/select_granule.py
  for s in scripts/*/download.py; do echo "== $s"; uv run "$s" || exit 1; done

# needs `just download` first
# Write website/image-data/ (COGs and layer specs) and website/catalog.json
build:
  for s in scripts/*/create-cog.py scripts/*/website-layers.py; do echo "== $s"; uv run "$s" || exit 1; done
  uv run scripts/website/build_catalog.py

# Rebuild website/vendor/ (deck.gl + deck.gl-raster) from scripts/website/vendor/package.json
vendor:
  cd scripts/website/vendor && npm ci && npm run build

# Developer documentation (VitePress) at http://localhost:5173/
docs:
  cd docs && npm ci && npm run dev

deploy:
  eval "$(aws s3 cp s3://ycgs-use1-terraform/ycgs/newhaven-multires-bucket - | jq -r '.outputs.deploy_commands.value')"

# Serve website/ at http://localhost:8000/ (Caddy: range requests, no caching; localhost only)
serve port="8000":
  PORT={{port}} caddy run --config scripts/website/Caddyfile --adapter caddyfile

# Example: just prefill-lookups --table <nasa lookup_table> --datasets hls-l30 --start 2024-01-01 (--help for options)
# Pre-fill the tiler's lookup cache with New Haven's CMR granule searches (docs/tiler/lookup-cache.md)
prefill-lookups *args:
  cd tiler && AWS_REGION="${AWS_REGION:-us-west-2}" uv run python -m ycgs_titiler.prefill {{args}}

# Rebuild just the ICESat-2 data for the website
is2:
  uv run scripts/icesat2/download.py
  uv run scripts/icesat2/create-cog.py
