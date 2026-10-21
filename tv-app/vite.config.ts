import legacy from "@vitejs/plugin-legacy";
import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

// config.xml is the single source of the app version (Home Assistant reads it too).
const appVersion =
  /<widget\b[^>]*\bversion="([^"]+)"/.exec(readFileSync("public/config.xml", "utf8"))?.[1] ??
  "0.0.0";

export default defineConfig({
  // Tizen loads files from the package root, so asset paths must be relative.
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
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
