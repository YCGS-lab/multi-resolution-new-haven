#!/usr/bin/env bash
# End-to-end test of the website module (terraform/aws) as it is used in
# production: apply a tagged test deployment (terraform/aws/examples/test),
# deploy website/ with the module's own deploy_commands and deploy user/role,
# check what the viewer relies on (HTTPS, index, catalog, HTTP range requests
# on the COGs), then destroy everything and sweep. ~30 min (CloudFront).
#
# Usage: scripts/aws-tests/site.sh [--keep]   (--keep: skip the destroy; run
#        scripts/aws-tests/destroy.sh <run-id> later)
source "$(dirname "$0")/lib.sh"

keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

require_minutes 30
start_run site "$REPO/terraform/aws/examples/test"

log "apply"
tofu_init "$example" "$run_dir"
run_tofu "$example" "$run_dir" apply -input=false -auto-approve "${vars[@]}"
out() { run_tofu "$example" "$run_dir" output -raw "$1"; }
url="$(out url)"
bucket="$(out bucket)"

log "deploy website/ with the module's deploy user and role"
deploy_website "$example" "$run_dir" "ycgs-test-site-$run_id"

log "checks against $url"
fail=0
check_website "$url" "$bucket"
((fail == 0)) || die "checks failed"
log "all checks passed"
