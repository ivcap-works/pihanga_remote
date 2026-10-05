"""One browser connection = one Session.

The session owns the card proxies of that browser tab. After every handled
message (and on explicit ``flush()``), it renders the card tree to JSON,
diffs it against what the browser has, and sends the JSON-Patch.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable, Optional

import jsonpatch
from pydantic import BaseModel, ValidationError

from .card import CardModel, EventContext, Flattener

log = logging.getLogger("pihanga_remote")

SendF = Callable[[dict[str, Any]], Awaitable[None]]
RouteHandler = Callable[["Session", list[str], dict[str, str]], Any]


class Session:
    """State of one browser tab.

    Concurrency model: everything runs on the server's asyncio event loop.
    Incoming messages of a session are handled one at a time (a per-session
    lock). ``async def`` handlers run on the loop; plain ``def`` handlers run in
    a worker thread by default (``sync_handlers="thread"``) so blocking code does
    not stall other tabs. Code outside handlers (background tasks, other HTTP
    endpoints) changes cards via ``await session.update(fn)`` or mutates them and
    calls ``await session.flush()``.
    """

    def __init__(self, send: SendF, *, sync_handlers: str = "thread"):
        self._send = send
        self._sync_handlers = sync_handlers
        self.cards: dict[str, CardModel] = {}
        self.state: dict[str, Any] = {}  # free-form per-session app state
        self.route_path: list[str] = []
        self.route_query: dict[str, str] = {}
        self.version = 0
        self.ack = 0  # highest client event seq processed
        self._sent: dict[str, Any] = {}
        self._sent_ack = 0
        self._by_name: dict[str, CardModel] = {}
        self._route_handlers: list[RouteHandler] = []
        self._fallback: Optional[Callable[..., Any]] = None
        self._close_handlers: list[Callable[["Session"], Any]] = []
        self._lock = asyncio.Lock()
        self._lock_owner: Optional[asyncio.Task[Any]] = None
        self._started = False
        self.closed = False

    # ------------------------------------------------------------------ building the UI

    def window(self, card: CardModel) -> CardModel:
        """Set the root card (rendered by the bundle as `_window`)."""
        self.cards["_window"] = card
        return card

    def add(self, name: str, card: CardModel) -> CardModel:
        """Give a card an explicit top-level name (otherwise names are derived)."""
        self.cards[name] = card
        return card

    def remove(self, name: str) -> None:
        self.cards.pop(name, None)

    def on_route(self, fn: RouteHandler) -> RouteHandler:
        """Register ``fn(session, path, query)`` called on browser navigation."""
        self._route_handlers.append(fn)
        return fn

    def on_close(self, fn: Callable[["Session"], Any]) -> Callable[["Session"], Any]:
        """Register ``fn(session)`` called when the browser disconnects."""
        self._close_handlers.append(fn)
        return fn

    async def close(self) -> None:
        self.closed = True
        for h in self._close_handlers:
            try:
                await _maybe_await(h(self))
            except Exception:
                log.exception("close handler failed")

    def on_unhandled_event(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """``fn(ctx)`` for events of cards without a handler for that event."""
        self._fallback = fn
        return fn

    # ------------------------------------------------------------------ rendering

    def render(self) -> dict[str, Any]:
        decls, by_name = Flattener(self.cards).run()
        self._by_name = by_name
        return decls

    def name_of(self, card: CardModel) -> Optional[str]:
        for n, c in self._by_name.items():
            if c is card:
                return n
        return None

    def snapshot(self) -> dict[str, Any]:
        doc = self.render()
        self.version += 1
        self._sent = doc
        self._sent_ack = self.ack
        return {"t": "snapshot", "version": self.version, "cards": doc, "ack": self.ack}

    def diff(self) -> Optional[dict[str, Any]]:
        doc = self.render()
        ops = jsonpatch.make_patch(self._sent, doc).patch
        if not ops and self.ack == self._sent_ack:
            return None
        base = self.version
        self.version += 1
        self._sent = doc
        self._sent_ack = self.ack
        return {"t": "patch", "base": base, "version": self.version, "ops": ops, "ack": self.ack}

    async def flush(self) -> None:
        """Send pending changes now.

        Message handlers flush automatically when they return; call this from
        background tasks, or inside a long-running async handler to show
        intermediate state (e.g. a spinner) before the handler finishes.
        """
        if self._lock_owner is not None and self._lock_owner is asyncio.current_task():
            await self._flush_locked()  # called from inside a handler of this session
            return
        async with self._locked():
            await self._flush_locked()

    async def update(self, fn: Callable[["Session"], Any]) -> None:
        """Run ``fn(session)`` (sync or async) exclusively with this session's
        event handling, then send the resulting patch. Use this to change a tab's
        cards from outside its own handlers (background tasks, broadcasts, REST
        endpoints)."""
        if self.closed:
            return
        if self._lock_owner is not None and self._lock_owner is asyncio.current_task():
            await _maybe_await(fn(self))
            await self._flush_locked()
            return
        async with self._locked():
            await _maybe_await(fn(self))
            await self._flush_locked()

    def _locked(self) -> "_OwnedLock":
        return _OwnedLock(self)

    async def _flush_locked(self) -> None:
        if not self._started or self.closed:
            return
        msg = self.diff()
        if msg:
            await self._send(msg)

    # ------------------------------------------------------------------ imperative commands

    async def dispatch(self, action: dict[str, Any]) -> None:
        """Dispatch a Redux action in the browser (e.g. for `pi/toast`)."""
        await self._send({"t": "dispatch", "action": action})

    async def toast(self, message: str, *, variant: str = "default", description: Optional[str] = None,
                    card: Optional[str] = None, **extra: Any) -> None:
        """Show a toast via a `pi/toast` card (declare one in your layout)."""
        a: dict[str, Any] = {"type": "toast/op/show", "message": message, "variant": variant, **extra}
        if description:
            a["description"] = description
        if card:
            a["cardName"] = card
        await self.dispatch(a)

    async def navigate(self, path: list[str], query: Optional[dict[str, str]] = None) -> None:
        """Change the browser URL (pushState) and run route handlers."""
        self.route_path, self.route_query = list(path), dict(query or {})
        await self._run_route_handlers()
        await self._send({"t": "navigate", "path": self.route_path, "query": self.route_query})

    # ------------------------------------------------------------------ incoming messages

    async def handle(self, msg: dict[str, Any]) -> None:
        async with self._locked():
            t = msg.get("t")
            if t == "hello":
                self._set_route(msg.get("route") or {})
                await self._run_route_handlers()
                self._started = True
                await self._send(self.snapshot())
                return
            if not self._started:
                log.warning("message before hello ignored: %s", t)
                return
            if t == "event":
                await self._handle_event(msg)
            elif t == "route":
                self._set_route(msg.get("route") or {})
                await self._run_route_handlers()
            elif t == "resync":
                log.info("client requested resync: %s", msg.get("reason"))
                await self._send(self.snapshot())
                return
            else:
                log.warning("unknown message type %r", t)
            await self._flush_locked()

    def _set_route(self, route: dict[str, Any]) -> None:
        self.route_path = list(route.get("path") or [])
        self.route_query = dict(route.get("query") or {})

    async def _run_route_handlers(self) -> None:
        for h in self._route_handlers:
            await _maybe_await(h(self, self.route_path, self.route_query))

    async def _handle_event(self, msg: dict[str, Any]) -> None:
        seq = int(msg.get("seq") or 0)
        self.ack = max(self.ack, seq)
        name = msg.get("card", "")
        event = msg.get("event", "")
        payload = msg.get("payload") or {}
        card = self._by_name.get(name)
        if card is None:
            log.warning("event %s for unknown card '%s' ignored", event, name)
            return
        ctx = EventContext(
            session=self, card=card, card_name=name, event=event, action_type=msg.get("type", ""),
            seq=seq, card_key=msg.get("cardKey"), raw=payload,
        )
        handler = card.handler_for(event)
        if handler is None:
            if self._fallback:
                await _maybe_await(self._fallback(ctx))
            else:
                log.debug("no handler for %s.%s", name, event)
            return
        ev: Any = payload
        model: Optional[type[BaseModel]] = type(card).__event_payloads__.get(event)
        if model is not None:
            try:
                ev = model.model_validate(payload)
            except ValidationError as e:
                log.warning("payload of %s.%s does not match %s: %s", name, event, model.__name__, e)
        try:
            if self._sync_handlers == "thread" and not _is_async(handler):
                # like FastAPI's `def` endpoints: blocking code must not stall the event loop
                # (a lambda that returns a coroutine is awaited back on the loop)
                await _maybe_await(await asyncio.to_thread(_call, handler, ev, ctx))
            else:
                await _maybe_await(_call(handler, ev, ctx))
        except Exception as e:  # keep the session alive
            log.exception("handler %s.%s failed", name, event)
            await self._send({"t": "error", "message": f"{name}.{event}: {e}"})


class _OwnedLock:
    """The session lock, remembering which task holds it (makes flush()/update()
    safe to call from inside a handler of the same session)."""

    def __init__(self, s: Session):
        self.s = s

    async def __aenter__(self) -> None:
        await self.s._lock.acquire()
        self.s._lock_owner = asyncio.current_task()

    async def __aexit__(self, *exc: Any) -> None:
        self.s._lock_owner = None
        self.s._lock.release()


def _is_async(fn: Callable[..., Any]) -> bool:
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None))


def _call(fn: Callable[..., Any], ev: Any, ctx: EventContext) -> Any:
    try:
        params = [
            p for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
        ]
    except (TypeError, ValueError):
        return fn(ev, ctx)
    if any(p.kind == p.VAR_POSITIONAL for p in params) or len(params) >= 2:
        return fn(ev, ctx)
    if len(params) == 1:
        return fn(ev)
    return fn()


async def _maybe_await(r: Any) -> Any:
    if inspect.isawaitable(r):
        return await r
    return r
