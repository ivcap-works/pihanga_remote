/**
 * Shared browser runtime for the script-tag / import-map setup.
 *
 *   npx vite build -c vite.runtime.config.ts   → dist-browser/runtime/*.js
 *
 * Every entry is an ES module. React lives in ONE shared chunk that all
 * entries import, so `react.js` (used by card libraries through the import
 * map) and `core.js` (the runtime) see the same React instance.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const src = (p: string) => fileURLToPath(new URL(`./src/browser/${p}`, import.meta.url));

export default defineConfig({
  plugins: [react()],
  // Library mode leaves process.env.* alone; browsers without a bundler have no `process`.
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist-browser/runtime",
    emptyOutDir: true,
    sourcemap: true,
    minify: true,
    lib: {
      entry: {
        react: src("react.ts"),
        "react-jsx-runtime": src("react-jsx-runtime.ts"),
        "react-dom": src("react-dom.ts"),
        "react-dom-client": src("react-dom-client.ts"),
        core: src("core.ts"),
      },
      formats: ["es"],
    },
    rollupOptions: {
      // Vite does not strip whitespace from ES library output by default; for a CDN bundle we want it minified.
      output: { entryFileNames: "[name].js", chunkFileNames: "chunks/[name]-[hash].js", minify: true },
    },
  },
});
