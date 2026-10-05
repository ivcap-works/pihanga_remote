/**
 * `<Card cardName=... parentCard=... />` for the lean runtime.
 *
 * Differences to @pihanga2/core's Card:
 *  - the declaration is read from `state.cards[cardName]` (plain JSON sent by
 *    the backend), there is no module-level card-instance registry;
 *  - no state mappers, no `onXxx` reducers, no anonymous/inline cards, no
 *    metacards — all of that is resolved by the backend;
 *  - every event is dispatched as a Redux action that the transport middleware
 *    forwards to the backend.
 */
import React, { useCallback, useMemo } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { UnknownAction } from "@reduxjs/toolkit";
import { metaCardTypes, resolveCardType } from "./registry";
import type { OverlayEntry, RemoteState } from "./store";
import type { CardDecl } from "./protocol";

export type CardProps = {
  cardName?: unknown;
  parentCard?: string;
  cardKey?: string;
  children?: React.ReactNode;
  [ctxtProp: string]: unknown;
};

/** Marker on actions created by card events, read by the transport middleware. */
export type CardEventAction = UnknownAction & {
  cardID: string;
  cardKey?: string;
  $event: string;
};

export function cls_f(cardName: string, cardComp: string, prefix = "pi") {
  // Same class-name scheme as @pihanga2/core so card CSS keeps working.
  const cn = cardName.replaceAll(/[^a-zA-Z0-9_-]/g, "_");
  const cp = cardComp.replaceAll(/[^a-zA-Z0-9_-]/g, "_");
  return (nodeName: string | string[], className?: string): string => {
    const na = typeof nodeName === "string" ? [nodeName] : nodeName;
    const ca: string[] = className ? [className] : [];
    na.forEach((n) => {
      const nn = n.replaceAll(/[^a-zA-Z0-9_-]/g, "_");
      ca.push(`${prefix}-${cn}-${nn}`, `${prefix}-${cp}-${nn}`);
    });
    return ca.join(" ");
  };
}

const EMPTY: Record<string, OverlayEntry> = {};

function Problem({ msg }: { msg: string }) {
  return (
    <div data-pihanga-problem="" style={{ color: "#b91c1c", fontSize: 12, fontFamily: "monospace" }}>
      {msg}
    </div>
  );
}

function CardImpl(props: CardProps): React.ReactNode {
  const { cardName, parentCard: _p, cardKey, children, ...ctxtProps } = props;
  const name = typeof cardName === "string" ? cardName : "";
  const decl = useSelector((s: RemoteState) => (name ? s.cards[name] : undefined));
  const overlay = useSelector((s: RemoteState) => (name ? s.overlay[name] : undefined)) ?? EMPTY;
  const dispatch = useDispatch();
  const cardType = decl ? resolveCardType(decl.cardType) : undefined;

  const handlers = useMemo(() => {
    const h: Record<string, (ev?: Record<string, unknown>) => void> = {};
    if (!cardType) return h;
    for (const [evName, actionType] of Object.entries(cardType.events)) {
      h[evName] = (ev?: Record<string, unknown>) => {
        const a: CardEventAction = { ...(ev ?? {}), type: actionType, cardID: name, $event: evName };
        if (cardKey !== undefined) a.cardKey = cardKey;
        dispatch(a);
      };
    }
    return h;
  }, [cardType, name, cardKey, dispatch]);

  const _dispatch = useCallback((a: UnknownAction) => dispatch(a), [dispatch]);
  const _cls = useMemo(() => cls_f(name, decl?.cardType ?? ""), [name, decl?.cardType]);

  if (cardName === undefined || cardName === null || cardName === "") return null; // empty slot
  if (typeof cardName !== "string") {
    return <Problem msg="inline card declarations are not supported by the remote runtime – declare the card in the backend and reference it by name" />;
  }
  if (!decl) return <Problem msg={`unknown card '${name}'`} />;
  if (!cardType) {
    const why = metaCardTypes[decl.cardType] ? "is a metacard (expand it in the backend)" : "is not in this bundle";
    return <Problem msg={`card type '${decl.cardType}' of '${name}' ${why}`} />;
  }

  // declaration props (minus runtime-only keys) < optimistic overlay < context props from parent
  const compProps: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(decl as CardDecl)) {
    if (k === "cardType" || k.startsWith("$")) continue;
    compProps[k] = v;
  }
  for (const [k, e] of Object.entries(overlay)) compProps[k] = e.value;
  Object.assign(compProps, ctxtProps);
  Object.assign(compProps, handlers, { cardName: name, cardKey, _cls, _dispatch });

  return React.createElement(cardType.component, compProps, children);
}

export const Card = React.memo(CardImpl);
