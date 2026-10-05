# Design — how pihanga-remote works internally

This document explains the internals: the browser runtime, the wire protocol,
the Python session/diffing machinery, how the typed card proxies are
generated, the script-tag deployment model, and what has been verified and
found along the way.

If you just want to build an app with the package, see
[HOW_TO_USE.md](HOW_TO_USE.md) instead.

## Table of contents

- [Overview](#overview)
- [How it works](#how-it-works)
  - [Browser](#browser-lean-runtime-710-kb-js--222-kb-gzip-including-all-shadcn-cards)
  - [Wire protocol](#wire-protocol-runtimesrcprotocolts)
  - [Local echo: why typing works](#local-echo-why-typing-works)
  - [Python side](#python-side)
- [Python proxies from the card library's types](#python-proxies-from-the-card-librarys-types)
- [Script-tag deployment](#script-tag-deployment-no-bundling-for-apps-or-card-libraries)
- [Verification](#verification)
- [Findings and limitations](#findings-and-limitations)

## Overview

The UI is a flat map `{cardName: declaration}` held in the browser's Redux
state. A Python backend owns that map. When the backend changes a card, it
sends **JSON Patch (RFC 6902)** ops over a WebSocket. When the user does
something, the browser sends the card event back over the same socket.

The browser loads one **prebuilt generic bundle** (runtime + every shadcn
card). App authors write Python only: no JS, no bundling, no Vite.

## How it works

### Browser (lean runtime, ~710 KB JS / 222 KB gzip including all shadcn cards)

* **One registry: card types.** Importing a card module calls
  `registerCardComponent`, and the shim records it. Card *instances* exist
  only in `state.cards`.
* **`<Card cardName>`** reads its declaration with
  `useSelector(s => s.cards[name])`, strips `cardType` and the `$…` keys, and
  adds the optimistic overlay. It then adds context props passed by the
  parent (for example `id` and `invalid` from `pi/field`, or `row` from
  `DataTable`), plus the `onXxx` handlers and `_cls` / `_dispatch`.
* **The patch reducer is pure.** Ops are applied on an Immer draft, so any
  card the patch doesn't touch keeps its object identity and doesn't
  re-render. On a version gap or a failed op, the cards stay untouched and
  the runtime asks for a snapshot.
* **Events.** Each `onXxx` dispatches `{type, cardID, cardKey?, $event,
  …payload}`. A middleware forwards that to the backend as `{t:"event", seq,
  card, event, type, payload}`.
* **`@pihanga2/core` is replaced at build time.** `vite.config.ts` aliases it
  to `src/core-shim.ts`. The shadcn 0.2.23 JS only imports these names from
  core: `Card, actionTypesToEvents, createCardDeclaration(2),
  createOnAction, createOnDispatch, registerActions, registerCardComponent,
  registerMetaCard, usePiReducer`.

### Wire protocol (`runtime/src/protocol.ts`)

| direction | message | purpose |
|---|---|---|
| ← | `snapshot {version, cards, ack}` | full state; sent on connect and on resync |
| ← | `patch {base, version, ops, ack}` | RFC 6902 ops, relative to `state.cards` |
| ← | `dispatch {action}` | imperative actions such as `toast/op/show` |
| ← | `navigate {path, query}` | `history.pushState` |
| → | `hello {route}` | on (re)connect |
| → | `event {seq, card, cardKey?, event, type, payload}` | card event |
| → | `route {route}` | browser back/forward |
| → | `resync {reason}` | version gap or a patch that couldn't be applied |

### Local echo: why typing works

shadcn's inputs are *controlled*: the component shows `props.value`. If every
keystroke has to go to Python and back before the input updates, fast typing
loses characters.

Each card can carry an event policy, `$events: {onChanged: {echo: {value:
"value"}, debounceMs?, send?}}`. When the event fires, the runtime
immediately overlays `props.value` with the typed value, tagged with the
event's `seq`. Each patch from the backend carries `ack`, the highest event
`seq` it has processed. The runtime keeps an overlay entry until `ack` covers
its `seq`, so typed text isn't overwritten by an older server value. The code
generator puts default policies from `schemas/shadcn.hints.json` on the
input-like cards (text-field, input, text-area, switch, checkbox, slider,
select, toggle-group, tabs).

I measured this against a backend whose handler takes 150 ms, typing `hello
world` with 20 ms between keys:

* **With echo:** the input showed `h, he, hel, …, hello world`, never going
  backwards.
* **Echo disabled:** the input showed `h, e, l, o, ' ', w, ho, hr, hl, hd`, so
  keystrokes were lost.

### Python side

* `Session` holds the named root cards. After every incoming message, and on
  `await session.flush()` from background tasks, it:
  1. **flattens** the card tree. Card *instances* nested in props get
     deterministic names (`parent/prop`, `parent/prop/<i>`, the same scheme
     as core's inline cards). This is how "anonymous" cards are resolved in
     the backend: the browser only ever sees names.
  2. **dumps** the result to JSON, using the camelCase wire names.
  3. **diffs** it against what was last sent (`jsonpatch.make_patch`) and
     sends the patch with `ack`.
* Handlers are `on_<event>` fields on the proxies: `fn(ev)` or `fn(ev, ctx)`,
  sync or async. `ev` is the generated pydantic payload model; `ctx` gives
  the session, the card and its name, and the `cardKey`.
* `session.add(name, card)` gives a card an explicit name.
  `session.on_route(...)`, `session.navigate([...])`, `session.toast(...)`
  and `session.on_close(...)` cover routing, notifications and cleanup.
* `GenericCard(card_type_="acme/x", …, handlers={"onChanged": fn})` works for
  card types that have no generated proxy.

Everything runs on uvicorn's single asyncio event loop per worker process;
there is no extra thread per WebSocket, except that a plain `def` handler is
run in a worker thread (see [HOW_TO_USE.md](HOW_TO_USE.md) for what that
means for app authors, and for how to drive the server from your own
thread).

## Python proxies from the card library's types

**How I'd set it up:** each card library publishes a machine-readable
catalogue with its package, e.g. `cards.schema.json`. The catalogue lists
every card type with a JSON Schema for its props and for each event payload,
plus each event's action type. Backends generate typed proxies from that
catalogue. `pihanga-shadcn` now does exactly this as of 0.2.23 (see below) —
the pipeline described here also still works standalone, against any card
library that doesn't.

1. **`runtime/tools/extract-card-schemas.mjs`** runs in three steps:
   1. It imports each card module in Node with a *recording* stand-in for
      `@pihanga2/core`. This shows which declaration creates which
      `cardType`, and which `onXxx` maps to which action type.
   2. It reads the library's `.d.ts` with the TypeScript compiler API. For
      every `X: (p: PiMapProps<Props, S, Events>) => PiCardDef` it takes
      `Props` and `Events`.
   3. It runs `ts-json-schema-generator` on a scratch copy of the `.d.ts`
      tree in which `PiCardRef` is `string` and React types are opaque.

   Result: `schemas/shadcn.cards.json`, with **58 card types**. One problem
   is reported: `shad/file-drop` can't be imported in Node, but its types
   are still extracted.
2. **`python -m pihanga_remote.codegen`** turns the catalogue and the hints
   into `pihanga_remote/cards/shadcn.py`:
   * one `CardModel` subclass per card;
   * snake_case fields with camelCase aliases, and the TS doc comments as
     field descriptions;
   * `Literal[...]` for string unions;
   * `CardRef = str | CardModel` wherever the TS type is `PiCardRef`;
   * typed `on_<event>` handler fields, excluded from serialisation;
   * class metadata (`__card_type__`, `__events__`, `__event_payloads__`,
     `__default_events_policy__`).

Mutations don't need tracking hooks on the proxies ("proxy triggers"): the
session diffs a snapshot of the whole tree, which catches in-place list and
dict edits too. `validate_assignment=True` still checks types when you
assign.

**What should move into the card library:**

* ~~Step 1 is the fragile part: the pipeline has to *import* the cards to
  find their card types.~~ **Done upstream as of 0.2.23:** `pihanga-shadcn`
  now runs the equivalent of steps 1–3 as part of its own build
  (`scripts/schema/extract-card-schemas.mjs`, wired into
  `scripts/build-core.mjs`) and ships `cards.schema.json` with the npm
  package (`@pihanga2/shadcn/cards.schema.json`). Consumers can read that
  file directly instead of deriving it themselves; the extractor in this
  repo (`runtime/tools/extract-card-schemas.mjs`) is kept only as a fallback
  for card libraries that don't publish a catalogue.
* The echo/debounce hints belong next to the cards too. The input cards know
  which prop mirrors which event field.
* Function-typed props (`DataTable` `format`, `cellClassName`, …) are dropped
  from the schema. They can't cross the wire, so the library could mark them
  as client-only.

## Script-tag deployment (no bundling for apps *or* card libraries)

Instead of one app bundle, the browser loads **separately published,
versioned ES modules** from a generic page (`browser/index.html`):

```html
<script type="importmap">{ "imports": {
  "react": "/pkg/@pihanga2/runtime@0.1.0/react.js",
  "react/jsx-runtime": "/pkg/@pihanga2/runtime@0.1.0/react-jsx-runtime.js",
  "react-dom": "/pkg/@pihanga2/runtime@0.1.0/react-dom.js",
  "@pihanga2/core": "/pkg/@pihanga2/runtime@0.1.0/core.js",
  "@pihanga2/shadcn": "/pkg/@pihanga2/shadcn@0.2.18/pihanga-shadcn.js",
  "acme-cards": "/pkg/acme-cards@0.1.0/acme-cards.js" } }</script>
<link rel="stylesheet" href="/pkg/@pihanga2/shadcn@0.2.18/pihanga-shadcn.css">
<script type="module">
  import { startRemote } from "@pihanga2/core";
  import "@pihanga2/shadcn"; import "acme-cards";
  startRemote();
</script>
```

* **Shared runtime** (`runtime/vite.runtime.config.ts`, 248 KB, 81 KB
  gzipped). It provides ES-module versions of React and ReactDOM, which npm
  only ships as CommonJS (generated by `tools/gen-react-facades.cjs`), plus
  `core.js`. All entries import one shared React chunk, so the import map
  pins exactly one React and one card registry for every library on the
  page.
* **Card library bundle** (`browser/pihanga-shadcn/`, drop-in files for the
  pihanga-shadcn repo; 562 KB, 154 KB gzipped including the precompiled
  CSS). It keeps only `react`, `react/jsx-runtime`, `react-dom` and
  `@pihanga2/core` external. The browser version of the shared runtime must
  export everything a card library imports from core; I check that the
  names match.
* **Third-party library without any build**
  (`browser/acme-cards/acme-cards.js`): plain ES module with
  `React.createElement`. It uses `useState` and embeds a shadcn card through
  `<Card>`. Its `cards.schema.json` is hand-written;
  `pihanga_remote/cards/acme.py` is generated from it.
* **Caching:** everything under `/pkg/<name>@<version>/` is served with
  `Cache-Control: public, max-age=31536000, immutable`, and `index.html`
  with `no-cache`. jsDelivr and unpkg serve npm packages at the same kind of
  versioned path.

Run it: `make cdn SHADCN=../pihanga-shadcn`, then `make demo-cdn` (port 8010)
and `make e2e-cdn`.

Things I only found by building it:

* **A CommonJS dependency calling `require("react")` breaks the ES
  module.** Radix's `react-use-is-hydrated` pulls in the CommonJS
  `use-sync-external-store/shim`, which calls `require("react")`. With React
  external, rolldown emits a runtime `require` that throws in the browser
  (*"Calling `require` for "react" in an environment that doesn't expose the
  `require` function"*). The drop-in maps it to React's built-in hook, and a
  build plugin fails the build if another such module appears. I checked
  that the plugin catches it.
* **Minification:** Vite doesn't minify ES library output unless asked;
  `output.minify: true` does it.
* **`process.env.NODE_ENV` must be `define`d.** Library mode leaves it
  untouched.
* **`<Toaster/>` must come from the framework card,** because a generic page
  has no app root. The drop-in wraps `shad/framework`; the proper fix is in
  `framework.component.tsx`.
* **The source build is not the npm package.** `make cdn
  SHADCN=../pihanga-shadcn` builds the script-tag bundle from a local
  checkout of `pihanga-shadcn`, not from the npm package used by the
  single-bundle flow. The two can drift (different commit, different card
  set) unless the checkout is kept in sync with the published version.

## Verification

* `runtime`: `tsc --noEmit` passes, and 9 vitest tests pass (patch ops
  including `move`/`copy`/`test`, structural sharing, version gaps, failed
  patches, overlay acknowledgement).
* `backend`: 12 pytest tests pass (flattening and naming, handler → patch +
  `ack`, echo policy, structure changes and resync, generic cards with
  async handlers, rejecting functions; `AppOptions` escaping and icon
  checks; title, icon and route precedence through the FastAPI app;
  WebSocket hello → snapshot; workers started and stopped with the server;
  `def` handlers running in a worker thread; `flush()` inside a handler not
  deadlocking; `session.update()`).
* `backend/tests/e2e/smoke.py` (Playwright/Chromium against the demo)
  passes all 9 steps: initial render, typing, switch, add row + toast,
  row-click toast, navbar navigation with URL change, back button, deep
  link to `/trucks`, and a clock pushed from the server every 10 seconds.
  No console errors and no render problems. It passes against **both**
  layouts: the single bundle and the script-tag layout.
* `backend/tests/e2e/script_tags.py` (script-tag layout) passes:
  1. one registry: 48 card types from both libraries;
  2. `acme/gauge` renders a `shad/badge` through `<Card>`;
  3. `useState` in the no-build library works (a second React copy would
     break hooks);
  4. an `acme` event reaches its Python handler and comes back as a patch;
  5. each of the 11 JS modules is fetched exactly once;
  6. on a second visit, 0 of 12 `/pkg` files are transferred over the
     network (all come from the browser cache).
* `backend/tests/e2e/background.py` (`examples/background.py`, two tabs)
  passes:
  1. title, description, theme-color, extra meta and icon (served as
     `image/svg+xml`) all appear in `<head>`;
  2. `GET /api/status`, defined after `create_app`, returns JSON while
     unknown paths return the page;
  3. the worker's broadcast reaches both tabs;
  4. `POST /api/announce` updates both tabs;
  5. while a blocking `def` handler held tab A for 3 s, tab B answered a
     click in 0.04 s and the worker kept ticking;
  6. an `async` handler showed "working…" through `flush()` before its
     result.
* **The published-package flow** (`app-template/` depending on
  `pihanga-remote` rather than a local checkout): built the wheel with
  `poetry build` and served it from a local package index standing in for
  PyPI. A copy of `app-template/` then ran `poetry install` and `poetry run
  python -m uvicorn my_app.main:app`, and a browser test typed a name,
  clicked a button twice and saw both updates, with no console errors.

## Findings and limitations

* **Tailwind classes sent from Python only work if they're in the bundle.**
  The CSS contains only classes found in the card library's sources.
  Workarounds: a `@source inline(...)` safelist in `runtime/src/index.css`,
  or using `style`.
* **Icons are a curated set**, 44 lucide icon names registered by name in
  `runtime/src/icons.ts`. Registering every lucide icon would work too, at a
  bundle-size cost.
* **Metacards (`pi/pageWithNavbarMeta`) can't run**, because their expansion
  is JS. The runtime shows an explanatory placeholder. The Python
  equivalent is an ordinary function that returns a card tree.
* **Cards nested by position get renamed when a list changes.** Inserting
  at the front of `Stack.content` shifts `parent/content/<i>` names.
  Rendering is still correct, but give cards that raise events an explicit
  name (`session.add`) or rely on a `cardKey` in the payload.
* **Diff cost is O(size of the UI) per commit.** That's fine for normal
  UIs; very large tables should be paged.
* **Not done:** authentication, multiple tabs sharing one session, sending
  events to the backend while it's offline (they're queued in memory only),
  and a way for a card to declare "self-managed" state (several shadcn
  cards already have a `selfManaged` prop, which fits this model well).
