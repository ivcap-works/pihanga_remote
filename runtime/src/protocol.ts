/**
 * Wire protocol between the lean runtime (browser) and a backend (e.g. Python).
 *
 * All messages are JSON objects with a `t` (type) discriminator.
 */

/** A card declaration as held in `state.cards[cardName]`. Plain JSON only. */
export type CardDecl = {
  cardType: string;
  /** Optional per-event policy, keyed by the card type's `onXxx` event name. */
  $events?: Record<string, EventPolicy>;
  [prop: string]: unknown;
};

export type EventPolicy = {
  /**
   * Optimistic local echo: `{ propName: payloadField }`. When the event fires,
   * the runtime immediately overlays `props[propName] = payload[payloadField]`
   * until the backend acknowledges the event (see `ack`).
   */
  echo?: Record<string, string>;
  /** Coalesce bursts of this event; only the last one within `debounceMs` is sent. */
  debounceMs?: number;
  /** `false` = never send this event to the backend. Default `true`. */
  send?: boolean;
};

export type CardMap = Record<string, CardDecl>;

/** RFC 6902 operation. */
export type JsonPatchOp =
  | { op: "add" | "replace" | "test"; path: string; value: unknown }
  | { op: "remove"; path: string }
  | { op: "move" | "copy"; from: string; path: string };

export type Route = { path: string[]; query: Record<string, string> };

// ---------------------------------------------------------------- server → client

export type SnapshotMsg = { t: "snapshot"; version: number; cards: CardMap; ack?: number };
export type PatchMsg = {
  t: "patch";
  base: number;
  version: number;
  ops: JsonPatchOp[];
  /** Highest client event `seq` whose effects are included in this version. */
  ack?: number;
};
/** Ask the runtime to dispatch a Redux action locally (e.g. show a toast). */
export type DispatchMsg = { t: "dispatch"; action: { type: string; [k: string]: unknown } };
/** Ask the runtime to change the browser URL (history.pushState). */
export type NavigateMsg = { t: "navigate"; path: string[]; query?: Record<string, string> };
export type ErrorMsg = { t: "error"; message: string };

export type ServerMsg = SnapshotMsg | PatchMsg | DispatchMsg | NavigateMsg | ErrorMsg;

// ---------------------------------------------------------------- client → server

export type HelloMsg = { t: "hello"; route: Route; version?: number };
export type EventMsg = {
  t: "event";
  seq: number;
  /** Card name (`cardID`) that raised the event. */
  card: string;
  /** Set when the card was rendered with a `cardKey` (e.g. per-row cards). */
  cardKey?: string;
  /** `onXxx` event name as declared by the card type (e.g. `onClicked`). */
  event: string;
  /** Redux action type (e.g. `pi/button/clicked`). */
  type: string;
  payload: Record<string, unknown>;
};
export type RouteMsg = { t: "route"; route: Route };
export type ResyncMsg = { t: "resync"; reason: string };

export type ClientMsg = HelloMsg | EventMsg | RouteMsg | ResyncMsg;
