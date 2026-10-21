import { defineConfig } from "vitest/config";

// One ES module, served by the integration at /samstream_files/samstream-card.js
// and added to every dashboard automatically (custom_components/samstream/frontend.py).
export default defineConfig({
  build: {
    lib: { entry: "src/samstream-card.ts", formats: ["es"], fileName: () => "samstream-card.js" },
    outDir: "../custom_components/samstream/frontend",
    emptyOutDir: true,
    target: "es2021",
  },
  test: {
    environment: "happy-dom",
  },
});
