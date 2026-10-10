# Vendored bundle

`website/vendor/` holds deck.gl and deck.gl-raster as files committed to the
repository, built by `scripts/website/vendor/`:

| File | What |
|---|---|
| `deck-gl-raster.js` | One minified ES module (~1.3 MB, ~0.38 MB gzipped): everything the site imports from npm |
| `geotiff-worker.js` | The tile-decoder worker (`@developmentseed/geotiff/pool/worker`) |
| `lerc-wasm.wasm` | The LERC decoder, loaded by the worker from next to itself |
| `versions.json` | Every npm package in the bundle, with its version |
| `*.LEGAL.txt` | License comments extracted by esbuild |

## What goes in

::: code-group
<<< @/../scripts/website/vendor/entry.js [scripts/website/vendor/entry.js]
:::

The site's modules import only from this entry point. (`CreateTexture` is
exported but no longer used; it can go at the next rebuild.)

## How it is built

::: code-group
<<< @/../scripts/website/vendor/build.mjs#bundle{js} [scripts/website/vendor/build.mjs#bundle]
<<< @/../scripts/website/vendor/build.mjs#lerc-wasm{js} [scripts/website/vendor/build.mjs#lerc-wasm]
:::

esbuild bundles the entry point and, separately, the decoder worker.
`module` is marked external: the `lerc` package imports Node's `module`
only when it runs under Node, never in the browser. The LERC WebAssembly
file is copied next to the bundles. `lerc` finds it relative to its own
script's URL, which is the worker's. `versions.json` is written from the
build's list of input files, so it shows exactly what went into the bundle.

```sh
just vendor            # = cd scripts/website/vendor && npm ci && npm run build
```

## Why bundle and commit <Badge type="warning" text="decision" />

::: warning Design decision
- **One copy of deck.gl.** deck.gl-raster is an npm package with deck.gl as
  a peer dependency, meaning it uses whatever deck.gl the page provides.
  Loading it from a CDN next to deck.gl's own browser build would load deck.gl
  and luma.gl twice, and the two copies do not work together.
- **No build step for the site.** The bundle is committed, so `serve.py` and
  `aws s3 sync` work on a fresh clone, with no Node.js installed.
- **Pinned versions.** `package.json` pins exact versions and
  `package-lock.json` locks the rest. deck.gl-raster is beta software that
  changes quickly, often with breaking changes. Updating is a deliberate
  step: [Updating deck.gl-raster](/deck-gl-raster#updating-deck-gl-raster).
- **Smaller download** than before: the old page loaded deck.gl's 2.1 MB
  browser build plus geotiff.js; see [Performance](/comparison/performance).

**Cost:** minified files in git. Their diffs are unreadable, so review an
update through `package.json`, `package-lock.json` and `versions.json`.
:::
