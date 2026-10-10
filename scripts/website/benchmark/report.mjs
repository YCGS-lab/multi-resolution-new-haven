// A Markdown table of bench.mjs results: medians per site, and the ratio of
// the last site to the first.
//
//   node report.mjs results.json [more.json ...]

import { readFileSync } from "node:fs";

const COLUMNS = {
  settleMs: ["time to settle", (v) => `${(v / 1000).toFixed(2)} s`],
  cogRequests: ["COG requests", (v) => v.toFixed(0)],
  cogBytes: ["COG bytes", (v) => `${(v / 1e6).toFixed(2)} MB`],
  blockingMs: ["main-thread blocking", (v) => `${v.toFixed(0)} ms`],
  frameP50: ["frame p50", (v) => `${v.toFixed(0)} ms`],
  frameP95: ["frame p95", (v) => `${v.toFixed(0)} ms`],
  bytes: ["JS + wasm", (v) => `${(v / 1e6).toFixed(2)} MB`],
  gzipBytes: ["gzipped", (v) => `${(v / 1e6).toFixed(2)} MB`],
  files: ["files", (v) => v.toFixed(0)],
};

for (const file of process.argv.slice(2)) {
  const { runs, latency, sites, results } = JSON.parse(readFileSync(file, "utf8"));
  const names = Object.keys(sites);
  console.log(`\n**${file.split("/").at(-1)}**: medians of ${runs} runs, ${latency ? `+${latency} ms latency per request` : "no added latency"}.\n`);
  const head = ["scenario", "metric", ...names, `${names.at(-1)} / ${names[0]}`];
  console.log(`| ${head.join(" | ")} |`);
  console.log(`|${head.map((_, i) => (i > 1 ? "---:" : "---")).join("|")}|`);
  for (const [label, bySite] of Object.entries(results)) {
    for (const k of Object.keys(bySite[names[0]].median).filter((k) => k in COLUMNS)) {
      const vals = names.map((n) => bySite[n].median[k]);
      const ratio = vals[0] ? `${(vals.at(-1) / vals[0]).toFixed(2)}x` : "";
      console.log(`| ${label} | ${COLUMNS[k][0]} | ${vals.map(COLUMNS[k][1]).join(" | ")} | ${ratio} |`);
    }
  }

}
