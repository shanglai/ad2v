// License gate for the whole npm tree (runtime + dev + transitive). Fails the build on copyleft
// (GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA) or OFL-only packages, and reports font files
// shipped by runtime dependencies. SPDX: `A OR B` passes if either side passes; `A AND B` needs
// both. Writes a JSON summary next to this script (scripts/licenses.json, gitignored by name).
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const FORBIDDEN = [/\bA?GPL/i, /\bLGPL/i, /\bMPL/i, /\bEPL/i, /\bCDDL/i, /CC-BY-SA/i, /\bOFL/i, /SIL Open Font/i];
const FONT_EXT = new Set([".ttf", ".otf", ".woff", ".woff2", ".eot"]);

function licenseOf(pkg) {
  let l = pkg.license ?? pkg.licenses ?? "UNKNOWN";
  if (Array.isArray(l)) l = l.map((x) => (typeof x === "string" ? x : x.type)).join(" OR ");
  if (typeof l === "object") l = l.type ?? "UNKNOWN";
  return String(l).trim();
}

function ok(expr) {
  const e = expr.replace(/[()]/g, " ").trim();
  if (/\bOR\b/i.test(e)) return e.split(/\bOR\b/i).some((p) => ok(p));
  if (/\bAND\b/i.test(e)) return e.split(/\bAND\b/i).every((p) => ok(p));
  return !FORBIDDEN.some((re) => re.test(e)) && e !== "UNKNOWN" && e !== "";
}

const seen = new Map();
function walk(dir) {
  const nm = path.join(dir, "node_modules");
  if (!fs.existsSync(nm)) return;
  for (const entry of fs.readdirSync(nm)) {
    if (entry.startsWith(".")) continue;
    const dirs = entry.startsWith("@") ? fs.readdirSync(path.join(nm, entry)).map((s) => path.join(nm, entry, s)) : [path.join(nm, entry)];
    for (const d of dirs) {
      const pj = path.join(d, "package.json");
      if (!fs.existsSync(pj)) continue;
      const pkg = JSON.parse(fs.readFileSync(pj, "utf8"));
      const key = `${pkg.name}@${pkg.version}`;
      if (!seen.has(key)) seen.set(key, { name: pkg.name, version: pkg.version, license: licenseOf(pkg), dir: d });
      walk(d);
    }
  }
}
walk(root);

function fonts(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory() && e.name !== "node_modules") fonts(p, out);
    else if (FONT_EXT.has(path.extname(e.name).toLowerCase())) out.push(p);
  }
  return out;
}
const runtime = Object.keys(JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).dependencies ?? {});
// informational: fonts inside runtime packages (e.g. three's examples/fonts) are never imported
const runtimeFonts = runtime.flatMap((n) => fonts(path.join(root, "node_modules", n))).map((p) => path.relative(root, p));
// the gate: no font file may reach the build output (labels use the browser's system font)
const distArg = process.argv.indexOf("--dist");
const distFonts = distArg > 0 ? fonts(path.resolve(root, process.argv[distArg + 1])).map((p) => path.relative(root, p)) : [];

const counts = {};
const bad = [];
for (const p of seen.values()) {
  counts[p.license] = (counts[p.license] ?? 0) + 1;
  if (!ok(p.license)) bad.push(`${p.name}@${p.version}: ${p.license}`);
}
const summary = { packages: seen.size, counts: Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1])), forbidden: bad, runtimeFontsNotImported: runtimeFonts, distFonts };
fs.writeFileSync(path.join(root, "scripts", "licenses.json"), JSON.stringify(summary, null, 2) + "\n");
console.log(`licenses: ${seen.size} packages`);
for (const [l, n] of Object.entries(summary.counts)) console.log(`  ${String(n).padStart(4)}  ${l}`);
if (runtimeFonts.length) console.log(`(info) font files inside runtime packages, not imported: ${runtimeFonts.join(", ")}`);
if (bad.length || distFonts.length) {
  console.error("FORBIDDEN:", bad.length ? bad : `font assets in the build output: ${distFonts.join(", ")}`);
  process.exit(1);
}
console.log(`licenses OK: no copyleft, no OFL/CC-BY-SA${distArg > 0 ? ", no font assets in the build output" : ""}`);
