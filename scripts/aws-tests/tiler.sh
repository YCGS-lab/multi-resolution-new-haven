#!/usr/bin/env bash
# End-to-end test of the tiler module (terraform/tiler): apply the complete,
# tagged test deployment (terraform/tiler/examples/test: three regional
# Lambda + HTTP API deployments behind CloudFront; the image is built with
# docker and pushed to each region's ECR), run the smoke test through
# CloudFront, then destroy everything and sweep. ~45 min (CloudFront, image).
#
# Credentials for the data (never printed or stored in state): the Earthdata
# login from ~/.netrc (urs.earthdata.nasa.gov) and the CDS API key from
# _credentials.toml, passed as ephemeral TF_VAR_* variables.
#
# Usage: scripts/aws-tests/tiler.sh [--keep]   (--keep: skip the destroy, e.g.
#        to try the website against it; then scripts/aws-tests/destroy.sh tiler-<run-id>)
source "$(dirname "$0")/lib.sh"

keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

docker buildx version >/dev/null 2>&1 || die "docker with buildx is needed (and running) to build the Lambda image"
command -v aws >/dev/null || die "the AWS CLI is needed (image push, version pruning)"
require_minutes 30

export_tiler_secrets

start_run tiler "$REPO/terraform/tiler/examples/test"

log "apply (builds and pushes the image)"
tofu_init "$example" "$run_dir"
run_tofu "$example" "$run_dir" apply -input=false -auto-approve "${vars[@]}"
url="$(run_tofu "$example" "$run_dir" output -raw url)"
apis=()
while read -r api; do apis+=("$api"); done < <(run_tofu "$example" "$run_dir" output -json deployments |
  python3 -c "import json,sys; [print(d['api_endpoint']) for d in json.load(sys.stdin).values()]")

log "smoke test against $url"
"$REPO/scripts/aws-tests/tiler-smoke.sh" "$url" "${apis[@]}" | tee "$run_dir/smoke.txt"
status=${PIPESTATUS[0]}
if ((status != 0)); then
  log "smoke test failed: recent logs (also in ${run_dir#$REPO/}/logs.txt)"
  for d in nasa:us-west-2 noaa:us-east-1 ecmwf:$(run_tofu "$example" "$run_dir" output -json deployments | python3 -c "import json,sys; print(json.load(sys.stdin)['ecmwf']['region'])"); do
    for g in "/aws/lambda/ycgs-test-tiler-$run_id-${d%%:*}" "/aws/apigateway/ycgs-test-tiler-$run_id-${d%%:*}"; do
      echo "--- $g (${d#*:})"
      aws logs filter-log-events --region "${d#*:}" --log-group-name "$g" --start-time $((($(date +%s) - 3600) * 1000)) \
        --query 'events[-20:].message' --output text 2>&1 | tr '\t' '\n' | cut -c1-600
    done
  done | tee "$run_dir/logs.txt"
  die "smoke test failed"
fi
log "all checks passed"
