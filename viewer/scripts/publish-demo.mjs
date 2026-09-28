// Copy the single-file demo to docs/reports/P5-demo.html (the reviewer opens it by double-click).
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = path.join(here, "..", "demo-dist", "index.html");
const dst = path.join(here, "..", "..", "docs", "reports", "P5-demo.html");
fs.copyFileSync(src, dst);
console.log(`demo: ${dst} (${(fs.statSync(dst).size / 1e6).toFixed(2)} MB)`);
