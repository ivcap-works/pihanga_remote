# Drop-in "script tag" build for pihanga-shadcn

These files belong in the **pihanga-shadcn** repository. Copy them into the repo root, keeping the paths:

```
vite.browser.config.ts
src/browser/index.tsx                       entry: registers all core cards (scripts/core-cards.json)
src/browser/browser.css                     precompiled Tailwind: theme + card classes + utility safelist
src/browser/icons.ts                        curated named icons for declarations from outside JS
src/browser/use-sync-external-store-shim.ts ES-module replacement for a CommonJS dependency
src/browser/env.d.ts
```

Build with:

```bash
npx vite build --config vite.browser.config.ts
```

This writes `dist-browser/pihanga-shadcn.js` (one ES module) and `dist-browser/pihanga-shadcn.css`. The build doesn't touch the existing npm build (`vite.lib.config.ts`), and needs no new dependencies. I tested it against GitHub `main` at a3a5550 (package.json 0.2.18, 47 core cards, Vite 8.0.14, Tailwind 4.3.3). The output was 434 KB of JS (135 KB gzipped) and 143 KB of CSS (25 KB gzipped).

## Publishing

1. Add `dist-browser/` to the npm package, e.g. as `browser/`. jsDelivr and unpkg then serve it at immutable versioned URLs such as `https://cdn.jsdelivr.net/npm/@pihanga2/shadcn@<v>/browser/pihanga-shadcn.js`.
2. ~~Also publish `cards.schema.json`~~ — **done as of 0.2.23**: `pihanga-shadcn`'s own build now generates and publishes `cards.schema.json` (`@pihanga2/shadcn/cards.schema.json`), so backends can read it directly instead of running `pihanga-remote/runtime/tools/extract-card-schemas.mjs` themselves.

## What the build handles, and what I'd change in the source instead

| Issue | In this drop-in | Better upstream fix |
|---|---|---|
| `react`, `react/jsx-runtime`, `react-dom` and `@pihanga2/core` must be one shared copy per page | kept external; the page's import map provides them | none needed |
| `process.env.NODE_ENV` is left untouched in Vite library mode, and there is no `process` in a browser | `define` | none needed |
| A page without a bundler can't run Tailwind | `browser.css` is compiled at build time, with an `@source inline()` list of extra utilities | document the extra utility set as part of the API |
| `pi/toast` needs `<Toaster/>`, which currently lives in the *app* (`src/app.root.tsx`) | `index.tsx` re-registers `shad/framework` wrapped with `<Toaster/>` | render `<Toaster/>` inside `framework.component.tsx` |
| Declarations from outside JS can only name icons | `icons.ts` registers a curated set | agree on and document the icon set |
| `@radix-ui/react-use-is-hydrated` pulls in the CommonJS `use-sync-external-store/shim`, which calls `require("react")`. Once React is external, rolldown emits a runtime `require` that throws in the browser | alias to `use-sync-external-store-shim.ts`; the `no-external-require` plugin fails the build if another such module appears | none needed; keep the guard |
