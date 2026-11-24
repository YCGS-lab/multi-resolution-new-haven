#!/bin/bash
# Benchmark every variant, one after another (timings need the machine to themselves).
#   run_all.sh BUILD_DIR RESULTS_DIR [names...]
# BUILD_DIR holds p0/ v1/ ... v4/ tiler.zip and fn/<base>-<function>.zip (variants/fn_package.py).
set -uo pipefail
B=$1; R=$2; shift 2
names=${*:-p0 v1 v2 v3 v4 v5-v1 v5-v4 v6-v1 v6-v4}
cd "$(dirname "$0")"
run() { uv run -q --project ../../.. python run.py "$@" --out "$R"; }
for n in $names; do
  case $n in
    p0|v1|v2|v3|v4) run "$n" --pkg "$B/$n/tiler.zip" --cold 10 ;;
    v5-*) base=${n#v5-}; run "$n" --set-backends --cold 5 \
            --pkg-for nasa="$B/fn/$base-nasa.zip" --pkg-for noaa="$B/fn/$base-noaa.zip" \
            --pkg-for ecmwf="$B/fn/$base-ecmwf.zip" ;;
    v6-*) base=${n#v6-}; run "$n" --layout split --set-backends --cold 5 \
            --pkg-for nasa-raster="$B/fn/$base-nasa-raster.zip" --pkg-for nasa-xarray="$B/fn/$base-nasa-xarray.zip" \
            --pkg-for noaa-raster="$B/fn/$base-noaa-raster.zip" --pkg-for noaa-xarray="$B/fn/$base-noaa-xarray.zip" \
            --pkg-for ecmwf-xarray="$B/fn/$base-ecmwf-xarray.zip" ;;
  esac
  echo "== $n done"
done
