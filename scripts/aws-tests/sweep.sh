#!/usr/bin/env bash
# Prove that no AWS test resources are left: everything tagged ycgs:purpose=test
# (in every enabled region, via the Resource Groups Tagging API), plus a by-name
# check (prefix "ycgs-test-") of the resource types the tagging API misses or
# that carry no tags (IAM, CloudFront functions / cache policies / origin access
# controls, secrets pending deletion). Read-only; exits 1 if anything is found.
#
# Usage: scripts/aws-tests/sweep.sh [run-id]   (default: every test run)
source "$(dirname "$0")/lib.sh"

run_id="${1:-}"
refresh_creds
found=0
report() { # kind name
  printf '  LEFT: %-28s %s\n' "$1" "$2"
  found=1
}

filters=(Key=ycgs:purpose,Values=test)
[[ -n "$run_id" ]] && filters+=("Key=ycgs:test-run,Values=$run_id")
prefix="$TEST_PREFIX"
# Run ids appear in every name (ycgs-test-<kind>-<run-id>...)
match() { [[ "$1" == "$prefix"* && ( -z "$run_id" || "$1" == *"$run_id"* ) ]]; }

log "tagged resources (ycgs:purpose=test${run_id:+, ycgs:test-run=$run_id})"
regions="$(aws account list-regions --region-opt-status-contains ENABLED ENABLED_BY_DEFAULT \
  --query 'Regions[].RegionName' --output text)"
for r in $regions; do
  while read -r arn; do
    [[ -n "$arn" ]] || continue
    # The tagging API can list a deleted Secrets Manager secret or Lambda
    # version for a while; secrets are re-checked by name below.
    report "tagged ($r)" "$arn"
  done < <(aws resourcegroupstaggingapi get-resources --region "$r" --tag-filters "${filters[@]}" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n')
done

log "global resources by name ($prefix*)"
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do match "$u" && report "IAM user" "$u"; done
for x in $(aws iam list-roles --query 'Roles[].RoleName' --output text); do match "$x" && report "IAM role" "$x"; done
while IFS=$'\t' read -r id comment; do
  [[ -n "$id" ]] && match "$comment" && report "CloudFront distribution" "$id ($comment)"
done < <(aws cloudfront list-distributions --query 'DistributionList.Items[].[Id,Comment]' --output text)
for f in $(aws cloudfront list-functions --query 'FunctionList.Items[].Name' --output text); do match "$f" && report "CloudFront function" "$f"; done
for p in $(aws cloudfront list-cache-policies --type custom --query 'CachePolicyList.Items[].CachePolicy.CachePolicyConfig.Name' --output text); do
  match "$p" && report "CloudFront cache policy" "$p"
done
for o in $(aws cloudfront list-origin-access-controls --query 'OriginAccessControlList.Items[].Name' --output text); do
  match "$o" && report "CloudFront OAC" "$o"
done

log "regional resources by name ($prefix*) in the regions the tests use"
for r in us-east-1 us-west-2 eu-central-1; do
  for s in $(aws secretsmanager list-secrets --region "$r" --include-planned-deletion --query 'SecretList[].Name' --output text); do
    match "$s" && report "secret ($r)" "$s"
  done
  for f in $(aws lambda list-functions --region "$r" --query 'Functions[].FunctionName' --output text); do
    match "$f" && report "Lambda ($r)" "$f"
  done
  for e in $(aws ecr describe-repositories --region "$r" --query 'repositories[].repositoryName' --output text); do
    match "$e" && report "ECR repository ($r)" "$e"
  done
  for a in $(aws apigatewayv2 get-apis --region "$r" --query 'Items[].Name' --output text); do
    match "$a" && report "HTTP API ($r)" "$a"
  done
  for g in $(aws logs describe-log-groups --region "$r" --query 'logGroups[].logGroupName' --output text); do
    base="${g##*/}"
    match "$base" && report "log group ($r)" "$g"
  done
done
for b in $(aws s3api list-buckets --query 'Buckets[].Name' --output text); do
  match "$b" && report "S3 bucket" "$b"
done

if ((found)); then
  log "test resources remain (destroy the run with scripts/aws-tests/destroy.sh <run-id>)"
  exit 1
fi
log "clean: no test resources${run_id:+ for run $run_id}"
