import { resolve } from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      // The referential constraints are the shared contract and live in
      // packages/scenespec, implemented once per stack (ruling A).
      "@scenespec": resolve(__dirname, "../../packages/scenespec"),
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "node",
  },
});
