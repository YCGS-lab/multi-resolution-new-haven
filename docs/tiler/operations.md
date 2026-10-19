# Running and testing

## Locally

```sh
tiler/serve-local.sh          # http://localhost:8100/ (port optional)
```

::: code-group
<<< @/../tiler/serve-local.sh [tiler/serve-local.sh]
:::

The script runs the app under uvicorn with real credentials: the Earthdata
login from `~/.netrc` (machine `urs.earthdata.nasa.gov`; parsed by hand
because Python's `netrc` module refuses a file others can read) and the
CDS key from the repository's `_credentials.toml`. It enables titiler-cmr
but turns off direct S3 access, which only works inside us-west-2, so
Earthdata granules are read over HTTPS (slowly). For COGs behind Earthdata
Login (HLS, ASTER) GDAL must follow the login redirect, which it only does
with a cookie jar, hence `GDAL_HTTP_COOKIEFILE` / `GDAL_HTTP_COOKIEJAR`. No
origin check is set, so plain requests work:

```sh
curl 'http://localhost:8100/datasets'
curl -o t.png 'http://localhost:8100/datasets/goes19-abi/truecolor/tiles/WebMercatorQuad/6/18/23.png?datetime=2026-06-03T18:00Z'
```

The API docs are at `/api.html` (titiler-cmr's at `/cmr/api.html`). To try
the website's cloud-only datasets against it, open the locally served site
with `?cloud=1&service.tiler=http://localhost:8100`
([local development](/build/local)).

## Tests and checks

All run without AWS credentials:

```sh
cd tiler
uv run pytest                 # unit tests on synthetic files
uv run pytest -m live         # plus a real GOES tile from the public NOAA bucket
uv run ruff check . && uv run ruff format --check .

cd terraform/tiler
tofu init && tofu test        # plan with mocked providers
```

- **`test_presets.py`** resolves every render of the real `datasets.yaml`
  and checks the parameters of each time kind, with GOES listings replaced
  by a recorded set of keys ([examples](./time#tests)).
- **`test_readers.py`** runs the real readers on synthetic Zarr, NetCDF and
  HDF5 files: time steps as bands, several variables, expressions, the GOES
  projection, SMAP's group layout, Black Marble's lat/lon grid, the URL
  allowlist and the CDS key's scope.
- **`test_app.py`** exercises the whole app through FastAPI's `TestClient`
  ([application](./app#tests)).
- **`tests/plan.tftest.hcl`**: see [plan tests](./infrastructure#plan-tests).

`conftest.py` allows `file:///` URLs through the reader's allowlist and
writes the synthetic files: an hourly Zarr store shaped like the ERA5-Land
ARCO store and a two-variable NetCDF.

## On AWS: the test deployment

```sh
scripts/aws-tests/tiler.sh            # apply, smoke test, destroy, sweep (~45 min)
scripts/aws-tests/tiler.sh --keep     # keep it, e.g. to point the website at it
```

`tiler.sh` applies `terraform/tiler/examples/test` (the module with
`ycgs-test-tiler-<run id>` names, every resource tagged `ycgs:purpose=test`
with a delete-after date, ECMWF in eu-central-1 by default), runs the
smoke test through CloudFront, then destroys everything and runs
`sweep.sh` to prove nothing is left. It needs Docker with buildx and the
AWS CLI (the image build and version pruning run on your machine), and
reads the Earthdata login and CDS key the same way as `serve-local.sh`,
passing them as ephemeral `TF_VAR_*` variables.

::: code-group
<<< @/../scripts/aws-tests/tiler-smoke.sh [scripts/aws-tests/tiler-smoke.sh]
:::

The smoke test requests a tile of every preset over New Haven twice (the
second pass should be CloudFront hits) and prints the resolved time and
source headers; requests raw NPY tiles exactly as the website does; lists
available times; prints each region's latency to its data host; and checks
that the regional API endpoints refuse requests that bypass CloudFront. It
exits 1 if any check fails, and can be run on its own against any
deployment: `tiler-smoke.sh https://xxxx.cloudfront.net [api-endpoint ...]`.

## The persistent deployment

To deploy the tiler together with the website, wired to each other, use
[`terraform/complete`](/build/complete) instead.

It lives in `ycgs-aws-infra` as a thin stack calling this module by Git URL
at a tag, with its own S3 state, providers and tags; the test example is
its reference. Deploying a new version: tag this repository, bump `ref`
there, then plan and apply with OpenTofu ≥ 1.11, Docker with buildx and the
AWS CLI available. The plan shows a new image tag if anything under
`tiler/` changed; the apply builds and pushes it to the three regional
repositories, publishes new Lambda versions (SnapStart init reads the
secrets), moves `live`, and prunes old versions.

## Common changes

### Add or change a dataset

1. Edit `tiler/src/ycgs_titiler/datasets.yaml`: pick `deployment`,
   `backend` and a time kind, add renders. A new `/xarray` or `/cog` host
   needs its prefix in the [allowlist](./readers#the-url-allowlist).
2. `uv run pytest`: `test_every_render_resolves` covers every new render.
   Update the route table in `tests/plan.tftest.hcl`.
3. Apply: the changed file gives a new image tag, and the CloudFront route
   comes from the same file.
4. For the website: a `tiler_source` for the preset's `raw` render in the
   dataset's `website-layers.py` ([website](/website/time#this-repository-s-tiler)).

### Rotate a credential

Set the `TF_VAR_*` values and bump `secrets_version`. The secret gets a new
version, the function's environment changes, and a new Lambda version reads
it ([secrets](./infrastructure#secrets)).

### Roll back

Point `live` at a previous published version (the 3 newest are kept):

```sh
aws lambda update-alias --function-name <name>-nasa --name live --function-version N
```

The next apply moves the alias back to the version OpenTofu manages, so
revert the code too.

### Purge cached tiles {#purge}

Tiles for settled times stay in CloudFront for a year
([caching](./requests#caching)). If an upstream dataset was reprocessed or
corrected, purge it in this order, so CloudFront doesn't refill from a
stale granule list:

1. **Lookup cache** (CMR and GOES datasets): run the prune job of the
   dataset's deployment. It recomputes every settled entry and deletes the
   ones whose result changed ([lookup cache](./lookup-cache#invalidation-and-the-prune-job)).
2. **CloudFront**: invalidate the dataset's path, which drops every time
   and render of it at the edges and in Origin Shield:

   ```sh
   aws cloudfront create-invalidation --distribution-id <tiler distribution> --paths "/datasets/<id>/*"
   ```

   Invalidation matches the path; the time is in the query string, so the
   unit is a whole dataset. A wildcard path counts as one of the 1,000 free
   invalidation paths a month.
3. **Browsers** keep tiles a day (`max-age`), or until a reload.

The deployment stacks in `ycgs-aws-infra` wrap steps 1 and 2 as
`just purge <id>`.
