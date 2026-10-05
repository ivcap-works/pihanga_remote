"""FastAPI integration: serves the browser bundle, the `/ws` endpoint and app-wide hooks."""

from __future__ import annotations

import asyncio
import json
import logging
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional, Union

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .options import CDN_BUNDLE, SINGLE_BUNDLE, AppOptions
from .session import Session, _maybe_await

log = logging.getLogger("pihanga_remote")

BuildF = Callable[[Session], Union[None, Awaitable[None]]]
WorkerF = Callable[["Hub"], Awaitable[None]]

DEFAULT_BUNDLE = SINGLE_BUNDLE  # backwards compatible names
__all__ = ["create_app", "Hub", "get_hub", "AppOptions", "CDN_BUNDLE", "DEFAULT_BUNDLE"]

IMMUTABLE = "public, max-age=31536000, immutable"


class Hub:
    """App-wide view of all connected browser tabs (one per process).

    Use it from background workers and from your own FastAPI endpoints::

        await hub.broadcast(lambda s: s.state["banner"].__setattr__("text", "Maintenance at 5pm"))
    """

    def __init__(self, options: AppOptions):
        self.options = options
        self.sessions: set[Session] = set()

    async def broadcast(self, fn: Callable[[Session], Any]) -> int:
        """Run ``fn(session)`` for every live session (serialised with that
        session's own event handling) and send the resulting patches.
        Returns the number of sessions updated."""
        live = [s for s in list(self.sessions) if not s.closed]
        results = await asyncio.gather(*(s.update(fn) for s in live), return_exceptions=True)
        for s, r in zip(live, results):
            if isinstance(r, Exception):
                log.error("broadcast to a session failed: %r", r)
        return len(live)


def get_hub(app: FastAPI) -> Hub:
    """The :class:`Hub` of an app created with :func:`create_app`."""
    return app.state.pihanga


def create_app(
    build: BuildF,
    options: Optional[AppOptions] = None,
    *,
    workers: Iterable[WorkerF] = (),
    app: Optional[FastAPI] = None,
    bundle_dir: Optional[Union[str, Path]] = None,
) -> FastAPI:
    """Create (or extend) a FastAPI app serving a Pihanga UI.

    * ``build(session)`` is called once per browser tab: declare the cards and
      wire the event handlers.
    * ``options`` – page title, metadata, icon, bundle, handler execution
      (:class:`AppOptions`).
    * ``workers`` – ``async def worker(hub)`` coroutines started when the server
      starts and cancelled when it stops: the place for app-wide background
      processing (polling, queues, timers). ``hub.broadcast(fn)`` pushes changes
      to every open tab.
    * ``app`` – extend an existing FastAPI app (e.g. one with its own lifespan
      or API routes). Your own routes always take precedence over the UI: the
      bundle is served only for paths no route matched.
    """
    if options is None:
        options = AppOptions()
    if bundle_dir is not None:  # deprecated keyword, kept for compatibility
        warnings.warn("create_app(bundle_dir=…) is deprecated; use AppOptions(bundle=…)", DeprecationWarning, 2)
        options = options.model_copy(update={"bundle": Path(bundle_dir)})

    app = app or FastAPI(title=options.title)
    hub = Hub(options)
    app.state.pihanga = hub

    bundle = options.bundle_dir()
    index_file = bundle / "index.html"
    index_html = options.render_index(index_file.read_text()) if index_file.is_file() else None
    icon_url, icon_file = options.icon_url(), options.icon_file()

    # ------------------------------------------------------------ background workers
    worker_list = list(workers)
    if worker_list:
        inner = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(a: FastAPI) -> AsyncIterator[Any]:
            async with inner(a) as state:
                tasks = [asyncio.create_task(_run_worker(w, hub), name=getattr(w, "__name__", "worker")) for w in worker_list]
                try:
                    yield state
                finally:
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

        app.router.lifespan_context = lifespan

    # ------------------------------------------------------------ websocket
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()

        async def send(msg: dict[str, Any]) -> None:
            await ws.send_text(json.dumps(msg, separators=(",", ":")))

        session = Session(send, sync_handlers=options.sync_handlers)
        session.hub = hub  # type: ignore[attr-defined]
        hub.sessions.add(session)
        try:
            await _maybe_await(build(session))
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("non-JSON message ignored")
                    continue
                await session.handle(msg)
        except WebSocketDisconnect:
            pass
        finally:
            hub.sessions.discard(session)
            await session.close()

    # ------------------------------------------------------------ icon
    if icon_file is not None and icon_url is not None:
        icon_bytes, icon_type = icon_file.read_bytes(), options.icon_type()

        @app.get(icon_url, include_in_schema=False)
        async def icon() -> Response:
            return Response(icon_bytes, media_type=icon_type, headers={"Cache-Control": IMMUTABLE})

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        if icon_file is not None:
            return Response(icon_bytes, media_type=icon_type, headers={"Cache-Control": "public, max-age=86400"})
        return Response(status_code=204)

    # ------------------------------------------------------------ bundle + client-side routes
    # Served from the 404 handler, so any route the app defines (before or
    # after create_app) wins over the catch-all UI.
    async def not_found(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code != 404 or request.method not in ("GET", "HEAD") or "endpoint" in request.scope:
            return await http_exception_handler(request, exc)  # a real 404 from an app route
        path = request.url.path.lstrip("/")
        if path:
            f = (bundle / path).resolve()
            if f.is_file() and bundle.resolve() in f.parents and f.name != "index.html":
                # Versioned package folders and hashed Vite assets never change → cache forever.
                headers = {"Cache-Control": IMMUTABLE} if path.startswith(("pkg/", "assets/")) else None
                return FileResponse(f, headers=headers)
        if index_html is None:
            return JSONResponse({"error": f"bundle not found at {bundle} – build it first"}, status_code=500)
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

    app.add_exception_handler(StarletteHTTPException, not_found)  # type: ignore[arg-type]
    return app


async def _run_worker(w: WorkerF, hub: Hub) -> None:
    try:
        await w(hub)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("background worker %s crashed", getattr(w, "__name__", w))
