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

`download` runs the scene and granule selection first if their output is
missing, then every `download.py`. `build` runs every `create-cog.py` and
`website-layers.py`, then the catalog. Both stop at the first failure.
Figures are made by running a dataset's `visualize*.py` scripts directly.

## Fixtures without credentials

Most datasets need credentials (Earthdata, Planet, CDS, AWS). To work on
the website without them, build the datasets that need none (`prism`,
`goes-lst`, `ct-impervious-2023`, the image services; Landsat Level-2
without its pan band), plus the [fixtures](./benchmark#fixtures). The
fixtures cover every COG render path.
