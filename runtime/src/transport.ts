/**
 * WebSocket transport + Redux middleware.
 *
 * - server → client: snapshot / patch / dispatch / navigate messages become
 *   Redux actions (patch application itself is a pure reducer, see store.ts)
 * - client → server: card events (actions carrying `$event`) and route changes
 */
import type { Middleware, UnknownAction } from "@reduxjs/toolkit";
import type { ClientMsg, EventPolicy, Route, ServerMsg } from "./protocol";
import { A, type RemoteState, type RemoteStore } from "./store";
import type { CardEventAction } from "./card";

export type TransportOpts = {
  url: string;
  /** Initial reconnect delay in ms (doubles up to 10 s). */
  reconnectMs?: number;
  log?: boolean;
};

export class Transport {
  private ws?: WebSocket;
  private store?: RemoteStore;
  private queue: ClientMsg[] = [];
  private seq = 0;
  private delay: number;
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private closed = false;

  constructor(private opts: TransportOpts) {
    this.delay = opts.reconnectMs ?? 500;
  }

  nextSeq(): number {
    return ++this.seq;
  }

  attach(store: RemoteStore): void {
    this.store = store;
    this.connect();
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }

  send(msg: ClientMsg): void {
    if (this.opts.log) console.debug("[pihanga-remote] →", msg);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    else if (msg.t === "event") this.queue.push(msg); // hello/route are re-sent on connect anyway
  }

  /** Send `msg` after `ms` unless another message with the same key arrives first. */
  sendDebounced(key: string, ms: number, msg: ClientMsg): void {
    const old = this.timers.get(key);
    if (old) clearTimeout(old);
    this.timers.set(
      key,
      setTimeout(() => {
        this.timers.delete(key);
        this.send(msg);
      }, ms),
    );
  }

  private connect(): void {
    const store = this.store!;
    store.dispatch({ type: A.STATUS, status: "connecting" });
    const ws = new WebSocket(this.opts.url);
    this.ws = ws;
    ws.onopen = () => {
      this.delay = this.opts.reconnectMs ?? 500;
      store.dispatch({ type: A.STATUS, status: "open" });
      const s = store.getState() as RemoteState;
      // Always start from a fresh snapshot: simpler than replaying missed patches.
      ws.send(JSON.stringify({ t: "hello", route: s.route } satisfies ClientMsg));
      const q = this.queue;
      this.queue = [];
      q.forEach((m) => this.send(m));
    };
    ws.onmessage = (ev) => {
      let msg: ServerMsg;
      try {
        msg = JSON.parse(ev.data as string) as ServerMsg;
      } catch {
        console.error("[pihanga-remote] non-JSON message", ev.data);
        return;
      }
      if (this.opts.log) console.debug("[pihanga-remote] ←", msg);
      this.handle(msg);
    };
    ws.onclose = () => {
      store.dispatch({ type: A.STATUS, status: "closed" });
      if (this.closed) return;
      setTimeout(() => this.connect(), this.delay);
      this.delay = Math.min(this.delay * 2, 10_000);
    };
  }

  private handle(msg: ServerMsg): void {
    const store = this.store!;
    switch (msg.t) {
      case "snapshot":
        store.dispatch({ type: A.SNAPSHOT, version: msg.version, cards: msg.cards, ack: msg.ack });
        break;
      case "patch":
        store.dispatch({ type: A.PATCH, base: msg.base, version: msg.version, ops: msg.ops, ack: msg.ack });
        break;
      case "dispatch":
        store.dispatch(msg.action as UnknownAction);
        break;
      case "navigate": {
        const qs = new URLSearchParams(msg.query ?? {}).toString();
        const url = "/" + msg.path.map(encodeURIComponent).join("/") + (qs ? `?${qs}` : "");
        window.history.pushState(null, "", url);
        store.dispatch({ type: A.ROUTE, route: { path: msg.path, query: msg.query ?? {} }, fromServer: true });
        break;
      }
      case "error":
        console.error("[pihanga-remote] backend error:", msg.message);
        break;
    }
    const s = store.getState() as RemoteState;
    if (s.remote.needResync) {
      console.warn("[pihanga-remote] requesting snapshot:", s.remote.needResync);
      this.send({ t: "resync", reason: s.remote.needResync });
      store.dispatch({ type: A.RESYNC_SENT });
    }
  }
}

/** Forwards card events (and route changes) to the backend. */
export function transportMiddleware(t: Transport): Middleware {
  return (api) => (next) => (action) => {
    const a = action as Partial<CardEventAction>;
    if (typeof a.$event === "string" && typeof a.cardID === "string") {
      const state = api.getState() as RemoteState;
      const policy: EventPolicy = state.cards[a.cardID]?.$events?.[a.$event] ?? {};
      const { type, cardID, cardKey, $event, ...payload } = a as CardEventAction;
      const seq = t.nextSeq();
      if (policy.echo) {
        const props: Record<string, unknown> = {};
        for (const [prop, field] of Object.entries(policy.echo)) props[prop] = payload[field];
        api.dispatch({ type: A.ECHO, card: cardID, props, seq });
      }
      if (policy.send !== false) {
        const msg: ClientMsg = { t: "event", seq, card: cardID, event: $event, type, payload: stripNonJson(payload) };
        if (cardKey !== undefined) msg.cardKey = cardKey;
        if (policy.debounceMs) t.sendDebounced(`${cardID}|${cardKey ?? ""}|${$event}`, policy.debounceMs, msg);
        else t.send(msg);
      }
    }
    const r = next(action);
    if ((action as UnknownAction).type === A.ROUTE && !(action as { fromServer?: boolean }).fromServer) {
      t.send({ t: "route", route: (api.getState() as RemoteState).route });
    }
    return r;
  };
}

/** Event payloads may carry DOM objects/functions; only JSON crosses the wire. */
function stripNonJson(v: Record<string, unknown>): Record<string, unknown> {
  const seen = new WeakSet<object>();
  return JSON.parse(
    JSON.stringify(v, (_k, x) => {
      if (typeof x === "function" || typeof x === "symbol") return undefined;
      if (typeof x === "object" && x !== null) {
        if (seen.has(x)) return undefined;
        seen.add(x);
        if (typeof Node !== "undefined" && x instanceof Node) return undefined;
        if (typeof Event !== "undefined" && x instanceof Event) return undefined;
      }
      return x;
    }) ?? "{}",
  );
}

export function routeFromLocation(): Route {
  const u = new URL(window.location.href);
  const query: Record<string, string> = {};
  u.searchParams.forEach((v, k) => (query[k] = v));
  return { path: u.pathname.split("/").filter(Boolean).map(decodeURIComponent), query };
}
