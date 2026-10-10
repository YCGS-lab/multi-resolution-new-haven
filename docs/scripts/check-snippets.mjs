// Checks every code-snippet import (`<<< path#region`) in the docs: the file
// exists and, if a region is named, the file has exactly one matching
// `#region` / `#endregion` pair. (VitePress silently shows the whole file
// when a region is missing.) Also lists regions in the source that no page uses.
//
//   node scripts/check-snippets.mjs        (from docs/)

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const docs = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(docs, "..");

function* walk(dir, test) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".") && name !== ".vitepress") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p, test);
    else if (test(p)) yield p;
  }
}

// Same marker forms VitePress accepts (see its snippet plugin).
const MARKER = [
  /^\/\/ ?#?((?:end)?region) ([\w*-]+)$/,
  /^\/\* ?#((?:end)?region) ([\w*-]+) ?\*\/$/,
  /^<!-- #?((?:end)?region) ([\w*-]+) -->$/,
  /^# ?((?:end)?region) ([\w*-]+)$/,
];
function regions(file) {
  const found = new Map(); // name -> {start, end}
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, i) => {
      for (const re of MARKER) {
        const m = re.exec(line.trim());
        if (!m) continue;
        const r = found.get(m[2]) ?? {};
        if (m[1] === "region") r.start = (r.start ?? []).concat(i + 1);
        else r.end = (r.end ?? []).concat(i + 1);
        found.set(m[2], r);
      }
    });
  return found;
}

let errors = 0;
const used = new Map(); // file -> Set(region)
for (const md of walk(docs, (p) => p.endsWith(".md"))) {
  readFileSync(md, "utf8")
    .split("\n")
    .forEach((line, i) => {
      const m = /^\s*<<<\s+(\S+?)(?:#([\w*-]+))?(?:\{[^}]*\})?(?:\s|$)/.exec(line);
      if (!m) return;
      const where = `${relative(docs, md)}:${i + 1}`;
      const file = m[1].startsWith("@") ? join(docs, m[1].slice(1)) : resolve(dirname(md), m[1]);
      if (!existsSync(file)) {
        console.error(`${where}: no such file ${relative(repo, file)}`);
        errors++;
        return;
      }
      if (!m[2]) return;
      const r = regions(file).get(m[2]);
      if (!r?.start || !r?.end || r.start.length !== 1 || r.end.length !== 1 || r.end[0] < r.start[0]) {
        console.error(`${where}: region "${m[2]}" missing or malformed in ${relative(repo, file)}`);
        errors++;
        return;
      }
      if (!used.has(file)) used.set(file, new Set());
      used.get(file).add(m[2]);
    });
}

// Regions defined in source but never shown (likely stale).
const sources = [...walk(join(repo, "scripts"), (p) => /\.(py|mjs|js)$/.test(p)), ...walk(join(repo, "website"), (p) => /\.(js|css|html)$/.test(p) && !p.includes("/vendor/")), ...walk(join(repo, "terraform"), (p) => p.endsWith(".tf"))];
for (const f of [...sources, join(repo, "justfile")]) {
  for (const name of regions(f).keys()) {
    if (!used.get(f)?.has(name)) console.warn(`unused region "${name}" in ${relative(repo, f)}`);
  }
}
if (errors) {
  console.error(`${errors} broken snippet(s)`);
  process.exit(1);
}
console.log(`snippets OK (${[...used.values()].reduce((n, s) => n + s.size, 0)} regions in ${used.size} files)`);
