# Fitting the tiler's zip package in 250 MB

Experiments behind the zip package's build (`tiler/Dockerfile`, `zip` target):
how far below Lambda's 250 MB limit for an unzipped package the tiler gets,
with which changes, and what each change does to cold starts, tile latency,
memory and output. The results are in [REPORT.md](REPORT.md).

| Path | What |
|---|---|
| `variants/variants.Dockerfile` | P0 (PR #6's package) and V1-V4 as build targets, smallest change first (context: `tiler/`) |
| `variants/build-all.sh` | builds them: `build-all.sh OUT_DIR [p0 v1 v2 v3 v4]` |
| `variants/dedupe.py` | V2: one copy of each native library several wheels bundle (patchelf) |
| `variants/fn_package.py` | V5/V6: one function's package, without the distributions it doesn't import |
| `snapshot/snapshot_proxy.py` | mitmproxy addon: records every HTTPS read the tiler makes, then replays it offline |
| `bench/requests.py` | the request set: every dataset preset, 4 zooms over New Haven, a styled render and `raw` |
| `bench/record.py` | runs the request set in-process through the proxy (records the snapshot) |
| `bench/lambda_run.py`, `bench/run.py`, `bench/run_all.sh` | runs packages in the Lambda Python 3.14 image (Runtime Interface Emulator): cold starts, warm passes, memory |
| `bench/compare.py` | each variant's responses against the baseline's |
| `bench/trace.py`, `bench/unused.py` | which distributions, modules and shared objects the request set loads |
| `bench/check_loadable.py` | loads every shared object of a package (run in the Lambda image) |
| `bench/tables.py` | the report's tables |

## Running them

Everything runs locally against a fixed snapshot of the real data; nothing is
deployed.

```bash
# 1. record the snapshot (needs Earthdata, CDS credentials; ~35 GB, mostly NISAR)
mitmdump -s snapshot/snapshot_proxy.py --set snapshot_dir=SNAP --set snapshot_mode=record \
  --set connection_strategy=lazy -p 8899 &
cat ~/.mitmproxy/mitmproxy-ca-cert.pem > ca.pem      # plus any CA your network needs
SNAPSHOT_CA=$PWD/ca.pem EARTHDATA_LOGIN_USER=... EARTHDATA_LOGIN_PASSWORD=... CDSAPI_KEY=... \
  uv run python bench/record.py REC          # repeat until all 174 requests succeed

# 2. replay offline from now on
mitmdump ... --set snapshot_mode=replay ...

# 3. build and benchmark
variants/build-all.sh OUT                                                 # P0 (PR #6's zip) and V1-V4
docker buildx build --target zip --output type=local,dest=OUT/vf ../..   # the chosen build
for f in nasa noaa ecmwf nasa-raster nasa-xarray noaa-raster noaa-xarray ecmwf-xarray; do
  for b in v1 v4; do python variants/fn_package.py OUT/$b/tiler.zip OUT/fn/$b-$f.zip --function $f; done
done
SNAPSHOT_CA=$PWD/ca.pem bench/run_all.sh OUT RESULTS
SNAPSHOT_CA=$PWD/ca.pem uv run python bench/run.py vf --pkg OUT/vf/tiler.zip --out RESULTS
for v in p0 v1 v2 v3 v4 vf; do     # peak memory: two passes, no cold starts, room to grow
  SNAPSHOT_CA=$PWD/ca.pem BENCH_NASA_LIMIT_MB=8192 uv run python bench/run.py mem-$v \
    --pkg OUT/$v/tiler.zip --cold 0 --out MEM
done
uv run python bench/compare.py RESULTS p0 v1 v2 v3 v4 v5-v1 v5-v4 v6-v1 v6-v4 vf
uv run python bench/tables.py OUT RESULTS MEM
```

Docker containers reach the proxy on the Docker host (`DOCKER_HOST_IP`,
default `172.17.0.1`).
