# Local development

```sh
just download && just build        # data, COGs, catalog (needs credentials for some datasets)
just serve                         # http://localhost:8000/
```

## Local server <Badge type="warning" text="decision" />

`just serve` runs [Caddy](https://caddyserver.com/) with
`scripts/website/Caddyfile`: it serves `website/` only (the site needs
nothing outside it), on localhost only, with `Cache-Control: no-cache` so a
rebuilt COG or catalog is seen at once.

::: code-group
<<< @/../scripts/website/Caddyfile [scripts/website/Caddyfile]
:::

::: warning Why not `python -m http.server`
COG readers fetch byte ranges (`Range: bytes=a-b`). Python's built-in
server ignores the header and sends the whole file, so every tile request
would download the whole 40 MB impervious-surface COG. Caddy's file server
answers ranges with `206 Partial Content` (including suffix ranges and `416`
for impossible ones) and sends `.wasm` as `application/wasm`, so browsers
can compile the LERC decoder while it downloads. (An earlier `serve.py`
did this in Python, serving the repository root.)
:::

To test the cloud-only datasets locally, run the tiler too
(`tiler/serve-local.sh`, port 8100) and open
`http://localhost:8000/?cloud=1&service.tiler=http://localhost:8100`.

## The justfile <Badge type="tip" text="standard" />

::: code-group
<<< @/../justfile [justfile]
:::

| Recipe | Does | Page |
|---|---|---|
| `download` | Picks the Landsat scene and NISAR granule if not yet picked, then runs every `download.py` | [Data pipeline](/pipeline/#running-it) |
| `build` | Runs every `create-cog.py` and `website-layers.py`, then writes `catalog.json` | [Data pipeline](/pipeline/#running-it) |
| `vendor` | Rebuilds `website/vendor/` | [Vendored bundle](./vendor) |
| `docs` | These pages at `http://localhost:5173/`, reloading on save | [Documentation site](./docs-site) |
| `deploy` | Runs `deploy_commands` from the production state in S3 | [Deployment](./deploy#deploy-identity) |
| `serve [port]` | This server | above |
| `prefill-lookups` | Pre-fills the tiler's lookup cache with New Haven's CMR searches | [Lookup cache](/tiler/lookup-cache#pre-filling-prefill-py) |
| `is2` | Downloads and rebuilds only the ICESat-2 data | [ICESat-2](/pipeline/datasets/vegetation-and-land-cover#icesat-2) |

`download` and `build` stop at the first failure. Figures are made by
running a dataset's `visualize*.py` scripts directly.

## Fixtures without credentials

Most datasets need credentials (Earthdata, Planet, CDS, AWS). To work on
the website without them, build the datasets that need none (`prism`,
`goes-lst`, `ct-impervious-2023`, the image services; Landsat's
`website-layers.py`, which reads Level-2 live, without the pan band), plus
the [fixtures](./benchmark#fixtures). The fixtures cover every COG render
path except band expressions.
