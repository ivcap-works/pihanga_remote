/**
 * vite.browser.config.ts — "script tag" build of @pihanga2/shadcn.
 *
 *   npx vite build --config vite.browser.config.ts
 *
 * Output: dist-browser/
 *   pihanga-shadcn.js    one ES module; registers all core cards on load
 *   pihanga-shadcn.css   precompiled Tailwind + theme (no Tailwind needed by the page)
 *   cards.schema.json    (optional, produced separately) card catalogue for backends
 *
 * Shared dependencies are EXTERNAL and must be provided by the page's import map
 * (one copy per page): react, react/jsx-runtime, react-dom, @pihanga2/core.
 * Everything else is bundled.
 */
import path from "path";
import {readFileSync} from "fs";
import {fileURLToPath} from "url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import {defineConfig, type Plugin} from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(path.join(__dirname, "package.json"), "utf-8"));
const {cards: CORE_CARDS} = JSON.parse(
  readFileSync(path.join(__dirname, "scripts/core-cards.json"), "utf-8"),
) as {cards: string[]};

/** `import "virtual:pihanga-core-cards"` → one side-effect import per core card. */
function coreCardsPlugin(): Plugin {
  const id = "virtual:pihanga-core-cards";
  return {
    name: "pihanga-core-cards",
    resolveId: (s) => (s === id ? "\0" + id : undefined),
    load: (s) =>
      s === "\0" + id ? CORE_CARDS.map((c) => `import "@/cards/${c}";`).join("\n") : undefined,
  };
}

export const SHARED = ["react", "react/jsx-runtime", "react-dom", "@pihanga2/core"];

/**
 * CommonJS dependencies that `require()` a SHARED module cannot be bundled into
 * an ES module (rolldown emits a runtime `require` that throws in browsers).
 * Fail the build instead of shipping a broken bundle, and name the culprit.
 */
function noExternalRequirePlugin(): Plugin {
  return {
    name: "no-external-require",
    generateBundle(_opts, bundle) {
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== "chunk") continue;
        if (chunk.code.includes("doesn't expose the `require` function")) {
          const cjs = Object.keys(chunk.modules).filter((m) => m.includes("node_modules") && /\/cjs\/|shim/.test(m));
          this.error(
            `${chunk.fileName}: a bundled CommonJS module require()s a shared external. ` +
              `Alias it to an ES module (see src/browser/use-sync-external-store-shim.ts). Suspects: ${cjs.join(", ")}`,
          );
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), coreCardsPlugin(), noExternalRequirePlugin()],
  resolve: {
    alias: [
      {
        find: /^use-sync-external-store\/shim(\/index\.js)?$/,
        replacement: path.resolve(__dirname, "src/browser/use-sync-external-store-shim.ts"),
      },
      {find: "@/lib", replacement: path.resolve(__dirname, "./src/lib")},
      {find: "@/registry", replacement: path.resolve(__dirname, "./src/components")},
      {find: "@", replacement: path.resolve(__dirname, "./src")},
    ],
  },
  define: {
    // Library mode leaves process.env.* alone; a page without a bundler has no `process`.
    "process.env.NODE_ENV": JSON.stringify("production"),
    __PKG_VERSION__: JSON.stringify(pkg.version),
  },
  publicDir: false,
  build: {
    outDir: "dist-browser",
    emptyOutDir: true,
    sourcemap: true,
    cssCodeSplit: false,
    lib: {
      entry: path.resolve(__dirname, "src/browser/index.tsx"),
      formats: ["es"],
      fileName: () => "pihanga-shadcn.js",
      cssFileName: "pihanga-shadcn",
    },
    rollupOptions: {
      external: SHARED,
      output: {minify: true},
    },
  },
});
