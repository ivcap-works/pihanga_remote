/**
 * Redux store for the lean runtime.
 *
 * State shape:
 *   cards   – { [cardName]: CardDecl }  ← owned by the backend, changed only by
 *             snapshot/patch messages
 *   overlay – optimistic local values per card prop, dropped once the backend
 *             acknowledges the event that produced them
 *   remote  – connection + versioning bookkeeping
 *   route   – current browser route (client-owned, reported to the backend)
 */
import { configureStore, type Middleware, type UnknownAction } from "@reduxjs/toolkit";
import { produce } from "immer";
import { applyJsonPatch, PatchError } from "./patch";
import type { CardMap, JsonPatchOp, Route } from "./protocol";

export type OverlayEntry = { value: unknown; seq: number };

export type RemoteState = {
  cards: CardMap;
  overlay: Record<string, Record<string, OverlayEntry>>;
  remote: {
    status: "connecting" | "open" | "closed";
    version: number; // -1 = no snapshot yet
    ack: number;
    needResync?: string;
    lastError?: string;
  };
  route: Route;
};

export const A = {
  SNAPSHOT: "pi/remote/snapshot",
  PATCH: "pi/remote/patch",
  STATUS: "pi/remote/status",
  ECHO: "pi/remote/echo",
  ROUTE: "pi/remote/route",
  RESYNC_SENT: "pi/remote/resync_sent",
} as const;

export type SnapshotAction = { type: typeof A.SNAPSHOT; version: number; cards: CardMap; ack?: number };
export type PatchAction = { type: typeof A.PATCH; base: number; version: number; ops: JsonPatchOp[]; ack?: number };
export type EchoAction = { type: typeof A.ECHO; card: string; props: Record<string, unknown>; seq: number };

export function initialState(route: Route): RemoteState {
  return {
    cards: {},
    overlay: {},
    remote: { status: "connecting", version: -1, ack: 0 },
    route,
  };
}

function dropAcked(overlay: RemoteState["overlay"], ack: number): RemoteState["overlay"] {
  let changed = false;
  const next: RemoteState["overlay"] = {};
  for (const [card, props] of Object.entries(overlay)) {
    const keep: Record<string, OverlayEntry> = {};
    let any = false;
    for (const [k, e] of Object.entries(props)) {
      if (e.seq > ack) {
        keep[k] = e;
        any = true;
      } else changed = true;
    }
    if (any) next[card] = Object.keys(keep).length === Object.keys(props).length ? props : keep;
  }
  return changed ? next : overlay;
}

export function rootReducer(state: RemoteState, action: UnknownAction): RemoteState {
  switch (action.type) {
    case A.SNAPSHOT: {
      const a = action as unknown as SnapshotAction;
      const ack = a.ack ?? state.remote.ack;
      return {
        ...state,
        cards: a.cards,
        overlay: dropAcked(state.overlay, ack),
        remote: { ...state.remote, version: a.version, ack, needResync: undefined },
      };
    }
    case A.PATCH: {
      const a = action as unknown as PatchAction;
      if (a.base !== state.remote.version) {
        return produce(state, (d) => {
          d.remote.needResync = `version gap: have ${state.remote.version}, patch base ${a.base}`;
        });
      }
      try {
        const cards = applyJsonPatch(state.cards, a.ops);
        const ack = a.ack ?? state.remote.ack;
        return {
          ...state,
          cards,
          overlay: dropAcked(state.overlay, ack),
          remote: { ...state.remote, version: a.version, ack, needResync: undefined },
        };
      } catch (e) {
        const msg = e instanceof PatchError ? e.message : String(e);
        return produce(state, (d) => {
          d.remote.needResync = `patch failed: ${msg}`;
          d.remote.lastError = msg;
        });
      }
    }
    case A.RESYNC_SENT:
      return produce(state, (d) => {
        d.remote.needResync = undefined;
      });
    case A.ECHO: {
      const a = action as unknown as EchoAction;
      return produce(state, (d) => {
        const o = (d.overlay[a.card] ??= {});
        for (const [k, v] of Object.entries(a.props)) o[k] = { value: v, seq: a.seq };
      });
    }
    case A.STATUS:
      return produce(state, (d) => {
        d.remote.status = (action as unknown as { status: RemoteState["remote"]["status"] }).status;
      });
    case A.ROUTE:
      return { ...state, route: (action as unknown as { route: Route }).route };
    default:
      return state;
  }
}

// ------------------------------------------------------------------ local listeners
// Backs `usePiReducer` for cards that react to actions locally (e.g. `pi/toast`).
// Listeners run AFTER the reducer and may have side effects (they are not reducers).

export type Listener = (state: RemoteState, action: UnknownAction, dispatch: (a: UnknownAction) => void) => void;
const listeners = new Map<string, Set<Listener>>();

export function addListener(type: string, l: Listener): () => void {
  const s = listeners.get(type) ?? new Set<Listener>();
  s.add(l);
  listeners.set(type, s);
  return () => {
    s.delete(l);
  };
}

const listenerMiddleware: Middleware = (api) => (next) => (action) => {
  const r = next(action);
  const a = action as UnknownAction;
  const ls = [...(listeners.get(a.type) ?? []), ...(listeners.get("*") ?? [])];
  for (const l of ls) {
    try {
      l(api.getState() as RemoteState, a, api.dispatch);
    } catch (e) {
      console.error("[pihanga-remote] listener failed", a.type, e);
    }
  }
  return r;
};

export function createStore(route: Route, extra: Middleware[] = []) {
  return configureStore({
    reducer: rootReducer as (s: RemoteState | undefined, a: UnknownAction) => RemoteState,
    preloadedState: initialState(route),
    middleware: (gdm) =>
      gdm({ serializableCheck: false, immutableCheck: false }).concat(listenerMiddleware, ...extra),
  });
}

export type RemoteStore = ReturnType<typeof createStore>;
