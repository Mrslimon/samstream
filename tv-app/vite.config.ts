import legacy from "@vitejs/plugin-legacy";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Tizen loads files from the package root, so asset paths must be relative.
  base: "./",
  plugins: [
    // Tizen 4.0 (2018) ships Chromium 56: no ES modules, so emit legacy chunks only.
    legacy({ targets: ["chrome >= 47"], renderModernChunks: false }),
  ],
  build: {
    outDir: "dist",
    assetsInlineLimit: 0,
  },
  test: {
    environment: "happy-dom",
  },
});
