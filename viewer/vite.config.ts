import { defineConfig } from "vitest/config";
import { viteSingleFile } from "vite-plugin-singlefile";

// `vite build`            -> dist/ (served by `ad2v view`, shipped in the Python wheel)
// `vite build --mode demo` -> demo-dist/index.html: one self-contained file with the fixture embedded
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: mode === "demo" ? [viteSingleFile()] : [],
  build: {
    outDir: mode === "demo" ? "demo-dist" : "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 4096,
    assetsInlineLimit: mode === "demo" ? 100_000_000 : 4096,
  },
  server: { fs: { allow: [".."] } }, // theme tokens live in ../schema/themes
  test: { include: ["tests/**/*.test.ts"], testTimeout: 30_000 },
}));
