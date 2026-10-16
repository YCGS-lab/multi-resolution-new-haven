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
