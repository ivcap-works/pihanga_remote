/**
 * Drop-in replacement for the parts of `@pihanga2/core` that card libraries
 * import at runtime. The bundler aliases `@pihanga2/core` to this module, so
 * published card packages (e.g. `@pihanga2/shadcn`) run unmodified.
 *
 * Surface used by @pihanga2/shadcn 0.2.23 (extracted from its compiled JS):
 *   Card, actionTypesToEvents, createCardDeclaration, createCardDeclaration2,
 *   createOnAction, createOnDispatch, registerActions, registerCardComponent,
 *   registerMetaCard, usePiReducer
 */
import { useEffect, useRef } from "react";
import type { UnknownAction } from "@reduxjs/toolkit";
import { addCardType, metaCardTypes } from "./registry";
import { addListener } from "./store";

export { Card } from "./card";

type AnyComp = React.ComponentType<any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export function registerCardComponent(decl: { name: string; component: AnyComp; events?: Record<string, string> }): void {
  addCardType({ name: decl.name, component: decl.component, events: decl.events ?? {} });
}

/** Metacards expand into other cards via JS mappers — not possible when the
 * declaration is plain data. Recorded only so the runtime can explain why. */
export function registerMetaCard(decl: { type: string; events?: Record<string, string> }): void {
  metaCardTypes[decl.type] = { type: decl.type, events: decl.events };
}

export function registerActions<T extends string>(namespace: string, actions: readonly T[]) {
  const ah: Record<string, string> = {};
  actions.forEach((a) => (ah[a.toUpperCase()] = `${namespace}/${a}`));
  return ah as { [S in Uppercase<T>]: string };
}

export function actionTypesToEvents(actionTypes: Record<string, string>): Record<string, string> {
  const r: Record<string, string> = {};
  for (const [k, v] of Object.entries(actionTypes)) {
    const n = k
      .split("_")
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase())
      .join("");
    r[`on${n}`] = v;
  }
  return r;
}

export function createCardDeclaration(cardType: string) {
  return (p: Record<string, unknown>) => ({ ...p, cardType });
}
export const createCardDeclaration2 = createCardDeclaration;

/** App-level reducer registration has no meaning in the remote runtime. */
export function createOnAction(actionType: string) {
  return () => {
    console.warn(`[pihanga-remote] on-action registration for '${actionType}' ignored (handle it in the backend)`);
  };
}

/**
 * Typed fire-and-forget dispatch, meant for an app's own JS to push events
 * into the Redux store directly (e.g. a stream adapter feeding a card's
 * model). The remote runtime never has local app JS: all state changes
 * arrive as JSON-patch ops from the backend, so this is a safe no-op.
 */
export function createOnDispatch(actionType: string) {
  return () => {
    console.warn(`[pihanga-remote] dispatch for '${actionType}' ignored (push state changes from the backend instead)`);
  };
}

/**
 * Card-local reaction to an action while the card is mounted (e.g. `pi/toast`
 * listening for `toast/op/show`). Runs after the reducer; side effects allowed.
 */
export function usePiReducer(
  eventType: string,
  mapper: (state: unknown, action: UnknownAction, dispatch: unknown) => void,
  _cardName: string,
  enabled = true,
): void {
  const ref = useRef(mapper);
  ref.current = mapper;
  useEffect(() => {
    if (!enabled) return;
    return addListener(eventType, (s, a, d) => ref.current(s, a, d));
  }, [eventType, enabled]);
}
