// Run a Python script with the repository's virtualenv if present (cross-platform), else `python`.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const repo = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..", "..");
const candidates = [
  path.join(repo, ".venv", "Scripts", "python.exe"),
  path.join(repo, ".venv", "bin", "python"),
  process.env.AD2V_PYTHON ?? "",
].filter((p) => p && fs.existsSync(p));
const py = candidates[0] ?? "python";
const r = spawnSync(py, process.argv.slice(2), { stdio: "inherit" });
process.exit(r.status ?? 1);
