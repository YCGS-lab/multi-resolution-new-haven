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
run_id="$(new_run_id)"
run_dir="$RUNS_DIR/site-$run_id"
example="$REPO/terraform/aws/examples/test"
mkdir -p "$run_dir"
echo "$example" >"$run_dir/example"
vars=(-var "run_id=$run_id" -var "delete_after=$(delete_after)")
echo "${vars[*]}" >"$run_dir/vars"
log "run $run_id (state: ${run_dir#$REPO/})"

# region cleanup-trap
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if ((keep)); then
    log "kept; destroy with: scripts/aws-tests/destroy.sh site-$run_id"
    exit "$status"
  fi
  log "destroy"
  if tofu_destroy "$example" "$run_dir" "${vars[@]}" && [[ "$(state_count "$example" "$run_dir")" == 0 ]]; then
    "$REPO/scripts/aws-tests/sweep.sh" "$run_id" && rm -rf "$run_dir"
  else
    log "DESTROY FAILED: re-run scripts/aws-tests/destroy.sh site-$run_id"
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM
# endregion cleanup-trap

log "apply"
tofu_init "$example" "$run_dir"
run_tofu "$example" "$run_dir" apply -input=false -auto-approve "${vars[@]}"
out() { run_tofu "$example" "$run_dir" output -raw "$1"; }
url="$(out url)"
bucket="$(out bucket)"

# region deploy-as-user
# Deploy exactly as documented: the deploy user's access key assumes the
# deploy role (profiles from the aws_config output), then deploy_commands.
log "deploy website/ with the module's deploy user and role"
export AWS_CONFIG_FILE="$run_dir/aws-config" AWS_SHARED_CREDENTIALS_FILE="$run_dir/aws-credentials"
out aws_config >"$AWS_CONFIG_FILE"
name="ycgs-test-site-$run_id"
umask 077
printf '[%s-deploy-user]\naws_access_key_id = %s\naws_secret_access_key = %s\n' \
  "$name" "$(out deploy_access_key_id)" "$(out deploy_secret_access_key)" >"$AWS_SHARED_CREDENTIALS_FILE"
(
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
  for i in $(seq 1 24); do # new IAM keys take a few seconds to work
    aws --profile "$name-deploy" sts get-caller-identity >/dev/null 2>&1 && break
    sleep 5
  done
  cd "$REPO"
  # The role's policy can take a minute to apply after it is created.
  cmds="$(out deploy_commands)"
  for i in $(seq 1 12); do
    bash -euo pipefail -c "$cmds" && exit 0
    echo "deploy failed (attempt $i); retrying in 15 s (IAM propagation)"
    sleep 15
  done
  exit 1
)
unset AWS_CONFIG_FILE AWS_SHARED_CREDENTIALS_FILE
# endregion deploy-as-user

# region checks
log "checks against $url"
fail=0
check() { # description, command...
  local d="$1"
  shift
  if "$@"; then echo "  ok    $d"; else echo "  FAIL  $d"; fail=1; fi
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
cog="$(cd "$REPO/website" && ls image-data/*.tif | head -1)"
check "index.html 200" test "$(status_of "$url")" = 200
check "catalog.json 200" test "$(status_of "${url}catalog.json")" = 200
check "http redirects to https" test "$(status_of "${url/https:/http:}")" = 301
check "COG range request 206 ($cog)" test "$(status_of -r 0-1023 "$url$cog")" = 206
check "range body is 1024 bytes" test "$(curl -s -r 0-1023 "$url$cog" | wc -c | tr -d ' ')" = 1024
check "bucket is not public" test "$(status_of "https://$bucket.s3.amazonaws.com/index.html")" = 403
check "objects carry the deploy cache-control" \
  bash -c "curl -sI '${url}catalog.json' | grep -qi 'cache-control: public, max-age=300'"
# endregion checks

((fail == 0)) || die "checks failed"
log "all checks passed"
