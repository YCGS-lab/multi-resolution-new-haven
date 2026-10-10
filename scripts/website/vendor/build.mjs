// Bundles entry.js (deck.gl + deck.gl-raster) into website/vendor/:
//   deck-gl-raster.js   the ES module imported by website/js/
//   geotiff-worker.js   the tile decoder worker (@developmentseed/geotiff/pool/worker)
//   lerc-wasm.wasm      LERC decoder, loaded next to whichever script decodes
//   versions.json       the resolved package versions in the bundle
//
//   cd scripts/website/vendor && npm ci && npm run build

import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "../../../website/vendor");
mkdirSync(out, { recursive: true });

// #region bundle
const common = {
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  legalComments: "linked",
  logLevel: "info",
  metafile: true,
  // lerc imports node:module only when running under Node.
  external: ["module"],
};
const main = await esbuild.build({ ...common, entryPoints: [join(here, "entry.js")], outfile: join(out, "deck-gl-raster.js") });
await esbuild.build({
  ...common,
  entryPoints: [join(here, "node_modules/@developmentseed/geotiff/dist/pool/worker.js")],
  outfile: join(out, "geotiff-worker.js"),
});
// #endregion bundle

// #region lerc-wasm
// lerc locates its wasm relative to import.meta.url, i.e. next to the bundle.
const require = createRequire(import.meta.url);
copyFileSync(require.resolve("lerc/lerc-wasm.wasm"), join(out, "lerc-wasm.wasm"));
// #endregion lerc-wasm

const pkgs = new Set();
for (const f of Object.keys(main.metafile.inputs)) {
  const m = f.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (m) pkgs.add(m[1]);
}
const versions = Object.fromEntries(
  [...pkgs].sort().map((p) => [p, JSON.parse(readFileSync(join(here, "node_modules", p, "package.json"), "utf8")).version]),
);
writeFileSync(join(out, "versions.json"), `${JSON.stringify(versions, null, 1)}\n`);
console.log(`${Object.keys(versions).length} packages -> website/vendor/versions.json`);
