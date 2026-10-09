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

deploy:
  eval "$(aws s3 cp s3://ycgs-use1-terraform/ycgs/newhaven-multires-bucket - | jq -r '.outputs.deploy_commands.value')"

preview:
  caddy file-server --browse --listen :8000
