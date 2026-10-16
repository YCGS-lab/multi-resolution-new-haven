#!/usr/bin/env bash
# Request each tiler dataset preset through CloudFront (status, time, the
# resolved scan/time), list available times, measure the latency from each
# regional deployment to its data host, and check that the regional API
# endpoints refuse requests that bypass CloudFront. Exits 1 if a check fails.
#
# Usage: scripts/aws-tests/tiler-smoke.sh https://xxxx.cloudfront.net [api-endpoint ...]
set -uo pipefail
url="${1:?usage: tiler-smoke.sh https://xxxx.cloudfront.net [api-endpoint ...]}"
shift
fail=0

expect() { # want got label
  if [[ "$2" == "$1" ]]; then echo "  ok    $3"; else echo "  FAIL  $3 (HTTP $2, want $1)"; fail=1; fi
}

echo "== healthz"
expect 200 "$(curl -s -o /dev/null -w '%{http_code}' "$url/healthz")" healthz

tile() { # dataset render z x y [query]
  local q="${6:-}" out code
  out="$(curl -sS -o /dev/null -D - -w '%{http_code} %{time_total}s' --max-time 60 \
    "$url/datasets/$1/$2/tiles/WebMercatorQuad/$3/$4/$5.png${q:+?$q}" | tr -d '\r')"
  code="$(tail -1 <<<"$out" | cut -d' ' -f1)"
  expect 200 "$code" "$1/$2 z$3 ${q:+?$q} ($(tail -1 <<<"$out" | cut -d' ' -f2))"
  grep -iE '^(x-ycgs-|x-cache)' <<<"$out" | sed 's/^/          /'
}

echo "== tiles over New Haven (each twice: the second should be a CloudFront hit)"
for pass in 1 2; do
  echo "-- pass $pass"
  tile nisar-gcov balanced 9 152 191
  tile smap-l4 rootzone 6 19 23
  tile hls-l30 truecolor 12 1218 1531
  tile hls-l30 ndvi 12 1218 1531
  tile goes19-abi truecolor 6 19 23 "datetime=2026-06-03T18:00Z"
  tile goes19-abi ir-clean 6 19 23
  tile goes19-lst celsius 7 37 47 "datetime=2026-06-03T18:00Z"
  tile era5-land-t2m celsius 6 19 23
  tile era5-land-t2m diff 6 19 23 "datetime=2026-07-20T09:00&datetime2=2026-07-20T17:00"
  tile viirs-blackmarble radiance 9 152 191 "datetime=2025"
  tile chirps-daily precip 6 19 23 "datetime=2026-07-29"
  tile aster-gdem elevation 10 304 381
done

echo "== raw NPY tiles, as the website requests them"
for p in "smap-l4/raw/tiles/WebMercatorQuad/6/19/23.npy?tilesize=512&datetime=2026-07-30T15:00:00Z/2026-07-30T17:59:59Z" \
  "viirs-blackmarble/raw/tiles/WebMercatorQuad/8/76/95.npy?tilesize=512&datetime=2025-01-01T00:00:00Z/2025-12-31T23:59:59Z" \
  "goes19-lst/raw/tiles/WebMercatorQuad/5/9/11.npy?tilesize=512&datetime=2026-06-03T18:00:00Z" \
  "chirps-daily/raw/tiles/WebMercatorQuad/4/4/5.npy?tilesize=512&datetime=2026-07-29T00:00:00Z"; do
  expect 200 "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$url/datasets/$p")" "${p%%\?*}"
done

echo "== available times"
for p in "goes19-abi/times" "era5-land-t2m/times?start=2026-07-20T00:00&end=2026-07-20T03:00" \
  "smap-l4/times?start=2026-07-30&end=2026-07-31" "chirps-daily/times?start=2026-07-01&end=2026-07-03"; do
  body="$(curl -s --max-time 60 "$url/datasets/$p")"
  [[ "$body" == *'"count":'* && "$body" != *'"count":0'* ]] && echo "  ok    $p: $(head -c 120 <<<"$body")" || {
    echo "  FAIL  $p: $(head -c 200 <<<"$body")"
    fail=1
  }
done

echo "== latency from each deployment to its data host"
for d in nisar-gcov goes19-abi era5-land-t2m; do
  echo "  $(curl -s --max-time 60 "$url/datasets/$d/latency")"
done

echo "== regional endpoints refuse requests that bypass CloudFront"
for api in "$@"; do
  expect 403 "$(curl -s -o /dev/null -w '%{http_code}' "$api/healthz")" "$api"
done

exit "$fail"
