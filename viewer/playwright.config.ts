import { defineConfig } from "@playwright/test";

// E2E over the single-file demo (docs/reports/P5-demo.html is a copy of demo-dist/index.html).
// Chromium only. SwiftShader keeps screenshots identical on machines without a GPU.
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    viewport: { width: 1400, height: 860 },
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
  },
});
