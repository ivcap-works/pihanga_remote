// Stand-in for @pihanga2/core that records what card modules register.
export const recorded = { cardTypes: {}, metaCards: {}, declarations: new Map() };
globalThis.__piRecorded = recorded;
export function registerCardComponent({ name, events }) { recorded.cardTypes[name] = { events: events ?? {} }; }
export function registerMetaCard({ type, events }) { recorded.metaCards[type] = { events: events ?? {} }; }
export function registerActions(ns, actions) { const r = {}; actions.forEach((a) => (r[a.toUpperCase()] = `${ns}/${a}`)); return r; }
export function actionTypesToEvents(at) {
  const r = {};
  for (const [k, v] of Object.entries(at)) r["on" + k.split("_").map((s) => s[0].toUpperCase() + s.slice(1).toLowerCase()).join("")] = v;
  return r;
}
export function createCardDeclaration(cardType) { const f = (p) => ({ ...p, cardType }); f.__cardType = cardType; return f; }
export const createCardDeclaration2 = createCardDeclaration;
export function createOnAction() { return () => {}; }
export function createOnDispatch() { return () => {}; }
export function createOnDispatchPipe() { return () => {}; }
export function usePiReducer() {}
export function Card() { return null; }
export function memo(_f, m) { return m; }
