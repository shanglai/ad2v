import { defineConfig } from "vitest/config";
import { viteSingleFile } from "vite-plugin-singlefile";

// `vite build`            -> dist/ (served by `ad2v view`, shipped in the Python wheel)
// `vite build --mode demo` -> demo-dist/index.html: one self-contained file with the fixture embedded
// `vite build --mode app`  -> app-dist/app.html: the MCP App (ui://ad2v/map), one self-contained file,
//                            no sql.js, no wasm, no data: everything comes through app-only tools (P6)
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: mode === "demo" || mode === "app" || mode === "host" ? [viteSingleFile()] : [],
  build: {
    outDir: mode === "demo" ? "demo-dist" : mode === "app" ? "app-dist" : mode === "host" ? "e2e/host/dist" : "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 4096,
    assetsInlineLimit: mode === "demo" || mode === "app" ? 100_000_000 : 4096,
    rollupOptions: mode === "app" ? { input: "app.html" } : mode === "host" ? { input: "e2e/host/host.html" } : undefined,
  },
  server: { fs: { allow: [".."] } }, // theme tokens live in ../schema/themes
  test: {
    // tests/mcp/* spawn the Python MCP server: run them with `npm run test:mcp`
    include: process.env.AD2V_TEST_MCP ? ["tests/mcp/**/*.test.ts"] : ["tests/**/*.test.ts"],
    exclude: process.env.AD2V_TEST_MCP ? [] : ["tests/mcp/**"],
    testTimeout: 120_000,
  },
}));
