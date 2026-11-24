#!/bin/bash
# Build the variants' zips: build-all.sh OUT_DIR [targets...] (default p0 v1 v2 v3 v4)
# DOCKER_BUILD overrides the build command (e.g. a wrapper that adds proxy settings).
set -uo pipefail
out=$1; shift
targets=${*:-p0 v1 v2 v3 v4}
cd "$(dirname "$0")/../../.."   # tiler/
for v in $targets; do
  ${DOCKER_BUILD:-docker buildx build} --platform "${PLATFORM:-linux/amd64}" \
    -f experiments/lambda-size/variants/variants.Dockerfile --target "$v" \
    --output "type=local,dest=$out/$v" . > "$out/$v-build.log" 2>&1
  echo "$v exit $? $(grep -oE 'tiler.zip: .*' "$out/$v-build.log" | tail -1)"
done
