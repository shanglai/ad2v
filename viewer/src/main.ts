// Entry point: pick a data source (the embedded demo, a URL from `ad2v view`, or a local file),
// then start the app. Nothing here talks to anything but that one file.
import wasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { LocalFileSource } from "./data/LocalFileSource";
import { App } from "./ui/app";
import { h } from "./ui/dom";
import "./style.css";

const root = document.getElementById("app")!;

async function open(bytes: Uint8Array): Promise<void> {
  root.replaceChildren();
  root.classList.remove("picker");
  const ds = await LocalFileSource.fromBytes(bytes, wasmUrl);
  await new App(root, ds).start();
}

function fail(msg: string): void {
  root.replaceChildren(h("div", { class: "error" }, h("h2", {}, "Cannot open this file"), h("p", {}, msg)));
}

function picker(): void {
  root.classList.add("picker");
  const input = h("input", { type: "file", accept: ".ad2v", "aria-label": "open an .ad2v file" });
  input.addEventListener("change", () => {
    const f = input.files?.[0];
    if (f) void f.arrayBuffer().then((b) => open(new Uint8Array(b))).catch((e) => fail(String(e)));
  });
  const zone = h("div", { class: "drop" }, h("h1", {}, "ad2v viewer"), h("p", {}, "Drop an .ad2v file here, or choose one:"), input,
    h("p", { class: "muted" }, "The file is read in this browser only; nothing is uploaded."));
  zone.addEventListener("dragover", (e) => e.preventDefault());
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = e.dataTransfer?.files?.[0];
    if (f) void f.arrayBuffer().then((b) => open(new Uint8Array(b))).catch((err) => fail(String(err)));
  });
  root.replaceChildren(zone);
}

async function boot(): Promise<void> {
  if (import.meta.env.MODE === "demo") {
    const { DEMO_AD2V_BASE64 } = await import("./generated/demo-data");
    const bin = atob(DEMO_AD2V_BASE64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return open(bytes);
  }
  const file = new URLSearchParams(location.search).get("file");
  if (file) {
    const r = await fetch(file);
    if (!r.ok) return fail(`${file}: HTTP ${r.status}`);
    return open(new Uint8Array(await r.arrayBuffer()));
  }
  picker();
}

boot().catch((e) => fail(e instanceof Error ? e.message : String(e)));
