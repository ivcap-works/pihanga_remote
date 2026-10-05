/**
 * Card-type registry. This is the ONLY registry in the lean runtime: card
 * *instances* live in the Redux state (`state.cards`), not here.
 */
import type React from "react";

export type CardTypeDef = {
  name: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: React.ComponentType<any>;
  /** `{ onClicked: "pi/button/clicked", ... }` */
  events: Record<string, string>;
};

export type MetaCardTypeDef = { type: string; events?: Record<string, string> };

export const cardTypes: Record<string, CardTypeDef> = {};
export const metaCardTypes: Record<string, MetaCardTypeDef> = {};

/**
 * Prefixes tried when a declaration uses an unqualified card type such as
 * `"pageWithNavbar"` (core resolves those against the "active framework").
 */
export const frameworkPrefixes: string[] = ["shad", "pi"];

export function addCardType(def: CardTypeDef): void {
  cardTypes[def.name] = def;
}

export function resolveCardType(name: string): CardTypeDef | undefined {
  const t = cardTypes[name];
  if (t) return t;
  for (const p of frameworkPrefixes) {
    const t2 = cardTypes[`${p}/${name}`];
    if (t2) return t2;
  }
  return undefined;
}

/** Machine-readable list of what this bundle can render (served to backends). */
export function manifest() {
  return {
    cardTypes: Object.values(cardTypes)
      .map((c) => ({ name: c.name, events: c.events }))
      .sort((a, b) => a.name.localeCompare(b.name)),
    unsupportedMetaCards: Object.keys(metaCardTypes).sort(),
  };
}
