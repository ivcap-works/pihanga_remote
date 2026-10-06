# How to build an app with pihanga-remote

This document is for app authors: building on the published `pihanga-remote`
package, writing `build(session)`, choosing where backend work goes, and
embedding the server in an existing process.

For how the package works internally (browser runtime, wire protocol,
codegen), see [DESIGN.md](DESIGN.md). For publishing a new `pihanga-remote`
release to PyPI (maintaining this repo, not building on the package), see
[README.md § Developing this repo](README.md#developing-this-repo).

## Table of contents

- [Quick example](#quick-example)
- [Building an app on the published package](#building-an-app-on-the-published-package)
- [App options](#app-options)
- [Icons](#icons)
- [Where backend processing goes](#where-backend-processing-goes)
- [Embedding the server: running uvicorn on its own thread](#embedding-the-server-running-uvicorn-on-its-own-thread)

## Quick example

```python
from pihanga_remote import create_app
from pihanga_remote.cards.shadcn import SdFramework, Stack, Typography, Button

def build(s):                                  # called once per browser tab
    count = Typography(text="0", level="h2")
    def inc(ev):                               # or inc(ev, ctx); may be async
        count.text = str(int(count.text) + 1)  # just mutate the proxy
    s.window(SdFramework(page=Stack(direction="column",
                                    content=[count, Button(label="+", on_clicked=inc)])))

app = create_app(build)
# save as mymod.py, then:  pip install pihanga-remote && python -m uvicorn mymod:app
#                          → open http://127.0.0.1:8000
```

`create_app(build, options=None, *, workers=(), app=None, bundle_dir=None)`
builds and returns a `FastAPI` instance **synchronously** — it just
registers routes, the `/ws` websocket handler, and (if `workers` is given) a
`lifespan` context. It does **not** start a server or block; nothing needs
"forcing" to make it return immediately. The server only starts, and only
then blocks a thread, once *you* hand the returned `app` to a uvicorn server
— whether that's `python -m uvicorn mymod:app`, `uvicorn.run(app)`, or the
`uvicorn.Server` API described below.

## Building an app on the published package

`pihanga-remote` is [on PyPI](https://pypi.org/project/pihanga-remote/), so
an app is just a Python project that depends on it. The package ships:
- the prebuilt browser bundles;
- the generated card classes for `@pihanga2/shadcn` (`pihanga_remote.cards.shadcn`);
- FastAPI and uvicorn (as dependencies).

An app needs no Node, npm, Vite or card-library checkout.

`app-template/` is a complete example. It needs exactly two files, plus an
empty `my_app/__init__.py`:

**`pyproject.toml`**
```toml
[project]
name = "my-app"
version = "0.1.0"
requires-python = ">=3.10,<4.0"
dependencies = ["pihanga-remote>=0.1,<0.2"]

[tool.poetry]
packages = [{ include = "my_app" }]

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
```

**`my_app/main.py`**: a `build(session)` function that declares the cards and
wires the handlers, plus `app = create_app(build, AppOptions(title="My
App", ...))`. See `app-template/my_app/main.py`, and "App options" and
"Where backend processing goes" below.

Run it:
```bash
poetry install
poetry run python -m uvicorn my_app.main:app --reload        # → http://localhost:8000
```

With pip instead of Poetry: `pip install pihanga-remote`, then `python -m
uvicorn my_app.main:app`.

To develop against unreleased changes instead of the published version, use
a local checkout: add `pihanga-remote = { path = "../backend", develop = true
}` under `[tool.poetry.dependencies]`.

What an app author needs to know:
- **Cards:** import the classes from `pihanga_remote.cards.shadcn`. Field
  names are snake_case, and the camelCase wire names also work. Handlers
  are the `on_<event>` fields; each receives the typed event payload and,
  optionally, an `EventContext`.
- **Nothing to build:** `AppOptions(bundle="single")` (the default) serves
  the single bundle; `AppOptions(bundle="script-tags")` serves the
  script-tag layout. Both are inside the wheel.
- **State is per browser tab, in memory, in one process.** Each WebSocket
  gets its own `Session`. Data shared between tabs (like `FLEET` in the
  demo) lives in module globals, so it is per worker process. With
  `--workers N` you'd need an external store, e.g. a database.
- **Card types not in the package** can be driven with
  `GenericCard(card_type_=…)`. The browser only renders card types that are
  in the bundle, so a new card library means a new bundle (see
  [DESIGN.md § Script-tag deployment](DESIGN.md#script-tag-deployment-no-bundling-for-apps-or-card-libraries)).

## App options

Everything about the page and the server that is not a card goes into one
model, `AppOptions`:

```python
from pathlib import Path
from pihanga_remote import AppOptions, create_app

app = create_app(build, AppOptions(
    title="Fleet monitor",                          # <title>
    description="Live status of the vehicle fleet", # <meta name="description">
    icon=Path(__file__).parent / "truck.svg",       # file, http(s) URL or data: URL
    theme_color="#2563eb",                          # <meta name="theme-color">
    lang="en",                                      # <html lang>
    meta={"author": "…", "robots": "noindex"},      # any further <meta name=… content=…>
    head_html=None,                                 # trusted raw HTML for <head> (analytics, fonts)
    bundle="single",                                # "single" | "script-tags" | Path to a bundle folder
    sync_handlers="thread",                         # where plain `def` handlers run: "thread" | "loop"
))
```

* **Page header:** the values are HTML-escaped (except `head_html`) and
  written into the bundle's `index.html` once, when the app is created.
* **Icon:** a local icon file is served at a content-hashed URL
  (`/_pihanga/icon-<hash>.svg`) that browsers may cache forever;
  `/favicon.ico` also returns it. Without an icon, `/favicon.ico` returns
  204 instead of the page.
* **Your routes come first:** the page and bundle files are served only for
  GET requests that no route matched. So `@app.get("/api/…")` routes work
  even when defined after `create_app`, and a 404 your own route raises
  stays a 404.
* **Old keyword:** `create_app(build, bundle_dir=…)` still works but is
  deprecated.

## Icons

Any card field typed as an icon name takes a plain **string name** from a
global icon registry, not a Python/JS class — e.g. `CollapsibleCard(icon=…)`,
`Attachment(icon=…)`, `JsonViewer(copy_icon=…)`, `PageWithNavbar(icon_name=…)`,
`FileDrop(icon=…)`, `ShadIcon(icon_name=…)`. The field is on the card itself
for most cards, but `Button` is different: `Button(icon_label=…)` replaces
the whole label with just an icon, while the icons shown before/after a
text label are nested one level down, in `opts`:
`Button(label="Delete", opts=PiButtonOpts(before_icon="trash"))`.
`PiButtonOpts` (mirroring `@/registry/ui/button.tsx`, alongside
`variant`/`size`/etc.) must be imported directly from
`pihanga_remote.cards.shadcn` — it isn't re-exported via `*`.

Pass the icon name as a string; if it isn't registered, the field is simply
ignored, or the card falls back to a hard-coded default (e.g.
`JsonViewer.copy_icon` falls back to `Copy`, `CollapsibleCard.icon` falls
back to `ChevronsUpDown` — see each field's docstring in
`pihanga_remote.cards.shadcn`).

The **single bundle** (the default, `AppOptions(bundle="single")`) ships a
curated set of 44 [Lucide](https://lucide.dev) icons, registered by name in
`runtime/src/icons.ts` (and mirrored for the script-tag build in
`browser/pihanga-shadcn/src/browser/icons.ts`):

```
plus, minus, x, check, down, chevron-down, chevron-up, chevron-left, chevron-right,
user, users, save, load, file-up, file-down, trash, pencil, search, settings,
refresh, info, warning, home, car, truck, star, heart, mail, calendar, clock,
download, upload, external-link, mountain-snow, play, pause, stop, filter, menu,
eye, eye-off, copy, log-in, log-out
```

For example `Button(opts=PiButtonOpts(before_icon="trash"))` renders
Lucide's `Trash2`, and `before_icon="chevron-right"` renders `ChevronRight`
— the string keys don't always match the Lucide component name 1:1, so
check the list above (or `runtime/src/icons.ts`) rather than guessing from
the Lucide docs.

A generic bundle can't know in advance which icons an app will need, so
only this curated set is included to keep the bundle small; registering
every Lucide icon would work too, at a bundle-size cost (see [DESIGN.md §
Findings and
limitations](DESIGN.md#findings-and-limitations)).

**Using an icon that isn't in the curated set:**
- With the single bundle, there's no way to add icons from Python alone —
  you'd need a custom bundle (out of scope for an app author; see
  [DESIGN.md § Script-tag
  deployment](DESIGN.md#script-tag-deployment-no-bundling-for-apps-or-card-libraries)).
- With `AppOptions(bundle="script-tags")`, you *can* add more icons without
  rebuilding anything: load an extra `<script type="module">` after the
  shadcn card bundle that calls `registerIcon(name, Component)` (exported
  from `@pihanga2/shadcn/cards/icons`) for whatever `lucide-react` icons (or
  any other React component) you need — the registry is the global
  `window._PihangaIcons`, so it's shared across every script on the page.

## Where backend processing goes

`build(session)` only sets up **one browser tab**. Everything runs on
uvicorn's single asyncio event loop per worker process; there is no extra
thread per WebSocket. Each tab's messages are handled one at a time, under a
per-session lock. With that model, the work splits into four places.
`examples/background.py` shows all four; run it with `make demo-bg`.

| Kind of work | Where it goes | How the UI gets updated |
|---|---|---|
| Reacting to the user in one tab | handlers wired in `build()` | automatically, when the handler returns |
| Slow or blocking work caused by the user | a plain `def` handler runs in a worker thread (`sync_handlers="thread"`, like FastAPI's `def` endpoints). An `async def` handler runs on the loop and can offload with `await asyncio.to_thread(...)` | automatically when it returns; call `await ctx.session.flush()` in an `async` handler to show intermediate state such as a spinner |
| App-wide background processing (polling, timers, queues, subscriptions) | `create_app(build, options, workers=[fn])`: `async def fn(hub)` starts with the server and is cancelled on shutdown | `await hub.broadcast(lambda s: …)` changes every open tab and sends the patches |
| Other entry points (REST, webhooks, CLI calls into the server) | normal FastAPI routes on the same `app` | `await get_hub(app).broadcast(...)`, or `await session.update(fn)` for a single tab |

Rules that follow from this:

* **Don't block the loop in `async def` code.** Use `await
  asyncio.to_thread(...)`, or write a plain `def` handler.
* **A `def` handler runs in a thread,** so it should only change its own
  tab's cards and plain data. To call the async session API (`toast`,
  `navigate`), use an `async def` handler.
* **Change cards from outside a handler with `session.update(fn)` or
  `hub.broadcast(fn)`.** These wait for any event that tab is currently
  handling, so the change never overlaps with a handler. Each tab saves
  what workers may touch in `session.state` (the example stores
  `session.state["sensor"]`).
* **Per-tab timers** (like the "connected for" clock) can simply be
  `asyncio.create_task(...)` in `build()`, cancelled with
  `session.on_close(...)`.
* **State lives per process.** The hub, the sessions and module-level data
  are per uvicorn worker. With `--workers N` or several replicas, use an
  external store or message bus (a database, Redis pub/sub, …) and let a
  worker in each process broadcast what it receives.

## Embedding the server: running uvicorn on its own thread

`create_app(...)` returns immediately — it's just a `FastAPI` instance, no
event loop is started, nothing blocks. The thing that blocks a thread is
*running* the app with uvicorn (`uvicorn.run(app)` or `python -m uvicorn
mymodule:app`), because that starts an event loop and blocks the calling
thread until the server stops. `pihanga_remote` never calls `uvicorn.run()`
itself — that's always left to you.

To integrate the UI into an existing, already-running (typically
synchronous) Python process without blocking its main thread, run uvicorn's
server in a background thread, using the lower-level `uvicorn.Server` API
(not the `uvicorn.run()` convenience wrapper, which doesn't return control to
you):

```python
import threading
import asyncio
import uvicorn

from pihanga_remote import create_app
from pihanga_remote.cards.shadcn import SdFramework, Stack, Typography, Button

def build(s):
    count = Typography(text="0", level="h2")
    def inc(ev):
        count.text = str(int(count.text) + 1)
    s.window(SdFramework(page=Stack(direction="column",
                                     content=[count, Button(label="+", on_clicked=inc)])))

app = create_app(build)   # returns immediately – just a FastAPI instance

config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
server = uvicorn.Server(config)

loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

def _run_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop_holder["loop"] = loop
    loop.run_until_complete(server.serve())

thread = threading.Thread(target=_run_server, daemon=True)
thread.start()

# ... your existing app continues to run here, unblocked ...

# later, to shut it down cleanly:
# server.should_exit = True
# thread.join()
```

Key points:

- `create_app()` is confirmed instantaneous/non-blocking — nothing to
  "force"; it's just object construction, no event loop involved. What
  blocks is `uvicorn.run(app)`; use `uvicorn.Server(config).serve()`
  instead — it's a coroutine, which you drive with your own event loop
  inside the spawned thread. This is uvicorn's documented way of embedding
  the server in another process.
- Each thread needs its own asyncio event loop, so create one with
  `asyncio.new_event_loop()` / `asyncio.set_event_loop(loop)` inside the
  thread target — don't try to reuse your main thread's loop (if it has
  one) across threads.
- `daemon=True` so the thread won't prevent your main program's process
  from exiting; otherwise call `server.should_exit = True` and
  `thread.join()` on shutdown.
- If your "existing app" is itself already async (e.g. another asyncio app
  running its own loop), you have a better option than threads: just
  `await server.serve()` as a task (`asyncio.create_task(server.serve())`)
  on your existing loop instead of spinning up a new OS thread — no
  GIL-thread overhead, and the `Hub`/`Session` broadcasting below
  interoperates with your other async code without cross-thread
  synchronization concerns. Only use the threading approach if your
  existing app is synchronous/blocking and can't be converted to asyncio.

### Thread-safe messaging into the UI

If you need to push updates into the UI (e.g. call `hub.broadcast(...)` or
`session.update(...)`) from your main (non-async) thread while the server
runs on its own thread, you must schedule the coroutine onto the *server's*
event loop rather than calling it directly — `Hub` and `Session` are
asyncio-only and are not thread-safe on their own:

```python
import asyncio
from pihanga_remote import get_hub

def announce(message: str) -> None:
    hub = get_hub(app)
    loop = loop_holder["loop"]          # captured when _run_server started
    future = asyncio.run_coroutine_threadsafe(
        hub.broadcast(lambda s: s.toast(message)), loop,
    )
    future.result(timeout=5)            # optional: wait for it / propagate exceptions
```

`asyncio.run_coroutine_threadsafe(coro, loop)` is the standard library's
mechanism for safely submitting a coroutine from any thread to a given
event loop and getting back a `concurrent.futures.Future` you can block on
or ignore. Use it for any call into `hub.broadcast(fn)` or
`session.update(fn)` made from outside the server's own thread.
