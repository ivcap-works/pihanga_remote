/**
 * acme-cards — a third-party Pihanga card library written WITHOUT any build
 * step: plain ES module, React.createElement, no JSX, no bundler.
 *
 * It imports React and @pihanga2/core by bare name; the page's import map
 * resolves them to the shared runtime. Proves that
 *  - hooks work (same React instance as the runtime and the shadcn cards),
 *  - there is one card registry (this card embeds a shadcn card via <Card>).
 */
import React, { useState } from "react";
import { Card, registerActions, actionTypesToEvents, registerCardComponent } from "@pihanga2/core";

const h = React.createElement;
export const ACME_GAUGE = "acme/gauge";
export const ACME_GAUGE_ACTION = registerActions(ACME_GAUGE, ["reset"]);

function Gauge({ label = "", value = 0, max = 100, badgeCard, cardName, onReset }) {
  const [hover, setHover] = useState(false); // would throw with a second React copy
  const pct = Math.max(0, Math.min(100, (100 * value) / max));
  return h(
    "div",
    {
      "data-pihanga": cardName,
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      style: { display: "flex", alignItems: "center", gap: 12, padding: "6px 0" },
    },
    h("span", { style: { fontSize: 13, minWidth: 90 } }, label),
    h(
      "div",
      { style: { width: 220, height: 10, borderRadius: 5, background: "#e5e7eb", overflow: "hidden" } },
      h("div", {
        "data-acme-gauge-bar": "",
        style: { width: `${pct}%`, height: "100%", background: hover ? "#2563eb" : "#60a5fa", transition: "width .3s" },
      }),
    ),
    h("span", { style: { fontSize: 12, fontVariantNumeric: "tabular-nums" } }, `${value}/${max}`),
    h("button", { type: "button", onClick: () => onReset({ value }), style: { fontSize: 12, textDecoration: "underline" } }, "reset"),
    // A card from ANOTHER library (e.g. shad/badge), rendered through the shared registry:
    badgeCard ? h(Card, { cardName: badgeCard, parentCard: cardName }) : null,
  );
}

registerCardComponent({ name: ACME_GAUGE, component: Gauge, events: actionTypesToEvents(ACME_GAUGE_ACTION) });
