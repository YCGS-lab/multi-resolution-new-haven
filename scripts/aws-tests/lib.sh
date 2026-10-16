# Shared helpers for the AWS test scripts (sourced, not run).
#
# Conventions every test follows:
#   - resources are created with OpenTofu only, from an example under terraform/,
#     with state in .aws-tests/<run-id>/ (kept until the destroy succeeds);
#   - every resource name starts with "ycgs-test-" and every taggable resource
#     carries ycgs:purpose=test, ycgs:test-run=<run-id>, ycgs:delete-after=<date>;
#   - a trap destroys the run on any exit, then sweep.sh checks nothing is left.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNS_DIR="$REPO/.aws-tests"
TEST_PREFIX="ycgs-test-"

log() { printf '\n\033[1m== %s\033[0m\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

new_run_id() { date -u +%Y%m%d-%H%M%S; }
delete_after() { date -u -v+1d +%Y-%m-%d 2>/dev/null || date -u -d '+1 day' +%Y-%m-%d; }

# region credentials
# Fresh role credentials from aws-sso when it is in use (AWS_SSO_PROFILE set by
# `aws-sso exec`/`eval`); otherwise whatever the environment already provides.
# aws-sso hands out its cached role credentials (valid up to 1 h) while they
# last, so ask for new ones when fewer than 45 min are left: one tofu apply or
# destroy runs on one set of credentials.
refresh_creds() {
  if [[ -n "${AWS_SSO_PROFILE:-}" ]] && command -v aws-sso >/dev/null; then
    eval "$(aws-sso eval --no-region -p "$AWS_SSO_PROFILE")"
    if (($(cred_minutes_left) < 45)); then
      eval "$(aws-sso eval --no-region --refresh -p "$AWS_SSO_PROFILE")"
    fi
  fi
}

# Minutes left on the current role credentials (aws-sso sets
# AWS_SSO_SESSION_EXPIRATION), or a large number when unknown.
cred_minutes_left() {
  python3 -c "
import datetime as dt, sys
v = sys.argv[1]
print(int((dt.datetime.fromisoformat(v) - dt.datetime.now(dt.UTC)).total_seconds() // 60) if v else 100000)
" "${AWS_SSO_SESSION_EXPIRATION:-}"
}

# Minutes left on the SSO login (aws-sso), or a large number when unknown.
sso_minutes_left() {
  if [[ -n "${AWS_SSO_PROFILE:-}" ]] && command -v aws-sso >/dev/null; then
    local left h m
    left="$(aws-sso list 2>/dev/null | sed -n 's/.*Expires in: *\([^]]*\)\].*/\1/p' | head -1)"
    h="$(grep -o '[0-9]*h' <<<"$left" | tr -d h || true)"
    m="$(grep -o '[0-9]*m' <<<"$left" | tr -d m || true)"
    echo $((${h:-0} * 60 + ${m:-0}))
  else
    echo 100000
  fi
}

# Refuse to start a run that could outlive the credentials (a run that cannot
# be destroyed leaves resources behind).
require_minutes() {
  local need="$1" left
  refresh_creds
  if (($(cred_minutes_left) < need)) && [[ -n "${AWS_SSO_PROFILE:-}" ]]; then
    eval "$(aws-sso eval --no-region --refresh -p "$AWS_SSO_PROFILE")"
  fi
  aws sts get-caller-identity --query Arn --output text >/dev/null || die "no working AWS credentials"
  left="$(sso_minutes_left)"
  [[ -n "$left" ]] || left=0
  # Either the role credentials outlast the whole run, or the SSO login does
  # (and the destroy gets fresh credentials).
  if (($(cred_minutes_left) < need)); then
    ((left >= need)) || die "AWS SSO login expires in ${left} min; this test needs ${need} min. Run 'aws-sso logout && aws-sso login' first."
    (($(cred_minutes_left) >= 45)) || die "could not get role credentials valid for 45 min"
  fi
  log "AWS: $(aws sts get-caller-identity --query Arn --output text) (${left} min left on the SSO login, $(cred_minutes_left) on the role credentials)"
}
# endregion credentials

# region tofu-run
# tofu in an example directory, with this run's local state and plugin cache.
# Usage: run_tofu <example-dir> <run-dir> <tofu args...>
run_tofu() {
  local dir="$1" run_dir="$2"
  shift 2
  TF_DATA_DIR="$run_dir/.terraform" tofu -chdir="$dir" "$@"
}

tofu_init() {
  local dir="$1" run_dir="$2"
  run_tofu "$dir" "$run_dir" init -input=false -reconfigure -backend-config="path=$run_dir/terraform.tfstate" >/dev/null
}

# Destroy with retries (CloudFront and Lambda deletions can need a second pass).
tofu_destroy() {
  local dir="$1" run_dir="$2"
  shift 2
  local i
  for i in 1 2 3; do
    refresh_creds || true
    if run_tofu "$dir" "$run_dir" destroy -input=false -auto-approve "$@"; then
      return 0
    fi
    log "destroy attempt $i failed; retrying in 30 s"
    sleep 30
  done
  return 1
}
# endregion tofu-run

# Resources left in state (empty when destroyed).
state_count() {
  local dir="$1" run_dir="$2"
  run_tofu "$dir" "$run_dir" state list 2>/dev/null | wc -l | tr -d ' '
}

# region tiler-secrets
# The tiler's credentials as ephemeral TF_VAR_* variables (never printed or
# stored in state): the Earthdata login from ~/.netrc
# (urs.earthdata.nasa.gov) and the CDS API key from _credentials.toml.
export_tiler_secrets() {
  eval "$(cd "$REPO" && python3 - <<'PY'
import shlex, tomllib
from pathlib import Path
out = {}
rc = Path.home() / ".netrc"
words = rc.read_text().split() if rc.exists() else []
for i, w in enumerate(words[:-1]):
    if w == "machine" and words[i + 1] == "urs.earthdata.nasa.gov":
        rest = words[i + 2 :]
        rest = rest[: rest.index("machine")] if "machine" in rest else rest
        entry = dict(zip(rest[::2], rest[1::2]))
        out["TF_VAR_earthdata_username"] = entry.get("login", "")
        out["TF_VAR_earthdata_password"] = entry.get("password", "")
creds = Path("_credentials.toml")
if creds.exists() and (key := tomllib.loads(creds.read_text()).get("cds_api_key")):
    out["TF_VAR_cds_api_key"] = key
for k, v in out.items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
  [[ -n "${TF_VAR_earthdata_username:-}" ]] || die "no urs.earthdata.nasa.gov login in ~/.netrc"
  [[ -n "${TF_VAR_cds_api_key:-}" ]] || die "no cds_api_key in _credentials.toml"
}
# endregion tiler-secrets

# region deploy-website
# Deploy website/ exactly as documented: the deploy user's access key (from
# the example's outputs) assumes the deploy role (profiles from aws_config),
# then deploy_commands. A freshly created role's policy can take a minute to
# apply, so the deploy is retried.
# Usage: deploy_website <example-dir> <run-dir> <site name>
deploy_website() {
  local example="$1" run_dir="$2" name="$3"
  local cfg="$run_dir/aws-config" creds="$run_dir/aws-credentials" cmds
  run_tofu "$example" "$run_dir" output -raw aws_config >"$cfg"
  (
    umask 077
    printf '[%s-deploy-user]\naws_access_key_id = %s\naws_secret_access_key = %s\n' "$name" \
      "$(run_tofu "$example" "$run_dir" output -raw deploy_access_key_id)" \
      "$(run_tofu "$example" "$run_dir" output -raw deploy_secret_access_key)" >"$creds"
  )
  cmds="$(run_tofu "$example" "$run_dir" output -raw deploy_commands)"
  (
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
    export AWS_CONFIG_FILE="$cfg" AWS_SHARED_CREDENTIALS_FILE="$creds"
    for i in $(seq 1 24); do # new IAM keys take a few seconds to work
      aws --profile "$name-deploy" sts get-caller-identity >/dev/null 2>&1 && break
      sleep 5
    done
    cd "$REPO"
    for i in $(seq 1 12); do
      bash -euo pipefail -c "$cmds" && exit 0
      echo "deploy failed (attempt $i); retrying in 15 s (IAM propagation)"
      sleep 15
    done
    exit 1
  )
}
# endregion deploy-website

# region start-run
# Start a test run of an example: run id, state directory (with what
# destroy.sh needs), and a trap that destroys the run on any exit (unless
# keep=1) and then sweeps. Sets run_id, run_dir, example and vars.
# Usage: start_run <kind> <example-dir>
start_run() {
  kind="$1"
  example="$2"
  run_id="$(new_run_id)"
  run_dir="$RUNS_DIR/$kind-$run_id"
  mkdir -p "$run_dir"
  echo "$example" >"$run_dir/example"
  vars=(-var "run_id=$run_id" -var "delete_after=$(delete_after)")
  echo "${vars[*]}" >"$run_dir/vars"
  log "run $run_id (state: ${run_dir#$REPO/})"
  trap cleanup_run EXIT INT TERM
}

cleanup_run() {
  local status=$?
  trap - EXIT INT TERM
  if ((${keep:-0})); then
    log "kept; destroy with: scripts/aws-tests/destroy.sh $kind-$run_id"
    exit "$status"
  fi
  log "destroy"
  if tofu_destroy "$example" "$run_dir" "${vars[@]}" && [[ "$(state_count "$example" "$run_dir")" == 0 ]]; then
    "$REPO/scripts/aws-tests/sweep.sh" "$run_id" && rm -rf "$run_dir"
  else
    log "DESTROY FAILED: re-run scripts/aws-tests/destroy.sh $kind-$run_id"
    status=1
  fi
  exit "$status"
}
# endregion start-run

# region checks
# check <description> <command...>: report ok / FAIL; a failure sets fail=1.
check() {
  local d="$1"
  shift
  if "$@"; then echo "  ok    $d"; else echo "  FAIL  $d"; fail=1; fi
}

status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

# What the viewer relies on, against a deployed website (url ends with "/").
check_website() {
  local url="$1" bucket="$2" cog
  cog="$(cd "$REPO/website" && ls image-data/*.tif | head -1)"
  check "index.html 200" test "$(status_of "$url")" = 200
  check "catalog.json 200" test "$(status_of "${url}catalog.json")" = 200
  check "http redirects to https" test "$(status_of "${url/https:/http:}")" = 301
  check "COG range request 206 ($cog)" test "$(status_of -r 0-1023 "$url$cog")" = 206
  check "range body is 1024 bytes" test "$(curl -s -r 0-1023 "$url$cog" | wc -c | tr -d ' ')" = 1024
  check "bucket is not public" test "$(status_of "https://$bucket.s3.amazonaws.com/index.html")" = 403
  check "objects carry the deploy cache-control" \
    bash -c "curl -sI '${url}catalog.json' | grep -qi 'cache-control: public, max-age=300'"
}
# endregion checks
