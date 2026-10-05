import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const shim = fileURLToPath(new URL("./src/core-shim.ts", import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // The whole trick: card libraries import "@pihanga2/core"; we hand them the lean shim.
    alias: [
      { find: /^@pihanga2\/core$/, replacement: shim },
    ],
    dedupe: ["react", "react-dom", "react-redux"],
  },
  optimizeDeps: { exclude: ["@pihanga2/shadcn"], include: ["lucide-react"] },
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 4000 },
  server: { proxy: { "/ws": { target: "ws://localhost:8000", ws: true } } },
});
