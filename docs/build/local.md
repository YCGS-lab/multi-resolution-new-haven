# Local development

```sh
just download && just build        # data, COGs, catalog (needs credentials for some datasets)
uv run scripts/website/serve.py    # http://localhost:8000/website/
```

## serve.py <Badge type="warning" text="decision" />

`scripts/website/serve.py` serves the repository root.

::: code-group
<<< @/../scripts/website/serve.py#range-requests [scripts/website/serve.py#range-requests]
:::

::: warning Why not `python -m http.server`
COG readers fetch byte ranges (`Range: bytes=a-b`). Python's built-in
server ignores the header and sends the whole file, so every tile request
would download the whole 40 MB impervious-surface COG. `serve.py` subclasses
`SimpleHTTPRequestHandler` to answer single ranges with `206 Partial
Content`, including suffix ranges (`bytes=-N`), and `416` for impossible
ranges. It also sets `.wasm` to `application/wasm`, so browsers can compile
the LERC decoder while it downloads, and sends `Cache-Control: no-cache`, so
a rebuilt COG or catalog is seen at once.
:::

`just preview` uses [Caddy](https://caddyserver.com/) instead. It also
serves ranges, but it serves the whole repository to the network: see
[Issues and improvements](/issues#preview-exposes-repo).

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
