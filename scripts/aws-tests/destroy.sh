#!/usr/bin/env bash
# Destroy a test run whose automatic cleanup failed or was skipped (--keep),
# then sweep. Without arguments, lists the runs that still have state.
#
# Usage: scripts/aws-tests/destroy.sh [<kind>-<run-id> ...]   e.g. site-20261016-131000
source "$(dirname "$0")/lib.sh"

if (($# == 0)); then
  ls "$RUNS_DIR" 2>/dev/null || true
  exit 0
fi
refresh_creds
status=0
for run in "$@"; do
  run_dir="$RUNS_DIR/$run"
  [[ -f "$run_dir/example" ]] || die "no state for $run in ${RUNS_DIR#$REPO/}"
  example="$(cat "$run_dir/example")"
  read -r -a vars <"$run_dir/vars"
  log "destroy $run"
  tofu_init "$example" "$run_dir"
  if tofu_destroy "$example" "$run_dir" "${vars[@]}" && [[ "$(state_count "$example" "$run_dir")" == 0 ]] &&
    "$REPO/scripts/aws-tests/sweep.sh" "${run#*-}"; then
    rm -rf "$run_dir"
  else
    status=1
  fi
done
exit "$status"
