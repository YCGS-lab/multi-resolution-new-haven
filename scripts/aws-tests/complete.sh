#!/usr/bin/env bash
# End-to-end test of terraform/complete: the website and the tiler deployed
# together (terraform/complete/examples/test). Deploys website/ with the
# site's deploy user and role, then checks the coupling (the served env.json
# points at this tiler and survives the deploy; the tiler allows the
# website's origin in CORS and no other), the website itself
# (check_website) and the tiler (tiler-smoke.sh); then destroys everything
# and sweeps. ~35 min (two CloudFront distributions, the tiler image).
#
# Usage: scripts/aws-tests/complete.sh [--keep]   (--keep: skip the destroy;
#        then scripts/aws-tests/destroy.sh complete-<run-id>)
source "$(dirname "$0")/lib.sh"

keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

docker buildx version >/dev/null 2>&1 || die "docker with buildx is needed (and running) to build the Lambda image"
command -v aws >/dev/null || die "the AWS CLI is needed (image push, version pruning, website deploy)"
require_minutes 40
export_tiler_secrets
start_run complete "$REPO/terraform/complete/examples/test"

log "apply (website and tiler; builds and pushes the tiler image)"
tofu_init "$example" "$run_dir"
run_tofu "$example" "$run_dir" apply -input=false -auto-approve "${vars[@]}"
out() { run_tofu "$example" "$run_dir" output -raw "$1"; }
url="$(out url)"
tiler="$(out tiler_url)"
bucket="$(out bucket)"
apis=()
while read -r api; do apis+=("$api"); done < <(run_tofu "$example" "$run_dir" output -json tiler_deployments |
  python3 -c "import json,sys; [print(d['api_endpoint']) for d in json.load(sys.stdin).values()]")

log "deploy website/ with the site's deploy user and role"
deploy_website "$example" "$run_dir" "ycgs-test-all-$run_id"

# region coupling-checks
log "coupling: website $url <-> tiler $tiler"
fail=0
origin="${url%/}"
env_json="$(curl -s "${url}env.json")"
check "env.json services.tiler is this tiler" test \
  "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["services"]["tiler"])' "$env_json")" = "$tiler"
check "env.json keeps the repository's other services" test \
  "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["services"]["titiler_cmr"])' "$env_json")" = \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["services"]["titiler_cmr"])' "$REPO/website/env.json")"
check "env.json is not cached" bash -c "curl -sI '${url}env.json' | grep -qi 'cache-control: no-cache'"
acao() { # Access-Control-Allow-Origin of a tiler request sent with Origin: $1
  curl -s -o /dev/null -D - -H "Origin: $1" "$tiler/datasets/chirps-daily/raw/tiles/WebMercatorQuad/4/4/5.npy?datetime=2026-07-29" |
    tr -d '\r' | grep -i '^access-control-allow-origin:' | cut -d' ' -f2-
}
check "tiler allows the website's origin" test "$(acao "$origin")" = "$origin"
check "tiler allows the local site (extra_cors_origins)" test "$(acao http://localhost:8000)" = "http://localhost:8000"
check "tiler does not allow other origins" test -z "$(acao https://example.org)"
places="$(out places_url)"
check "env.json services.places is this place search" test \
  "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["services"]["places"])' "$env_json")" = "$places"
places_acao() { # Access-Control-Allow-Origin of a place search sent with Origin: $1
  curl -s -o /dev/null -D - -H "Origin: $1" "$places/suggest?q=New%20Haven" | tr -d '\r' | grep -i '^access-control-allow-origin:' | cut -d' ' -f2-
}
check "place search allows the website's origin" test "$(places_acao "$origin")" = "$origin"
check "place search does not allow other origins" test -z "$(places_acao https://example.org)"
check "place search suggests New Haven" bash -c "curl -sf '$places/suggest?q=New%20Haven' | grep -q 'New Haven'"
# endregion coupling-checks

log "website"
check_website "$url" "$bucket"

log "tiler"
"$REPO/scripts/aws-tests/tiler-smoke.sh" "$tiler" "${apis[@]}" | tee "$run_dir/smoke.txt"
((PIPESTATUS[0] == 0)) || fail=1

((fail == 0)) || die "checks failed"
log "all checks passed"
