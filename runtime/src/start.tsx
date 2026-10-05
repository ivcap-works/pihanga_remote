import React from "react";
import ReactDOM from "react-dom/client";
import { Provider, useSelector } from "react-redux";
import { Card } from "./card";
import { A, createStore, type RemoteState, type RemoteStore } from "./store";
import { Transport, routeFromLocation, transportMiddleware } from "./transport";
import { manifest } from "./registry";

export type StartRemoteOpts = {
  /** WebSocket URL; defaults to `ws(s)://<current host>/ws`. */
  url?: string;
  /** Element to mount into; defaults to `#root`. */
  root?: HTMLElement;
  /** Extra React nodes rendered next to the card tree (e.g. `<Toaster/>`). */
  extras?: React.ReactNode;
  log?: boolean;
};

function Root({ extras }: { extras?: React.ReactNode }) {
  const status = useSelector((s: RemoteState) => s.remote.status);
  const hasWindow = useSelector((s: RemoteState) => s.cards._window !== undefined);
  return (
    <>
      {hasWindow ? <Card cardName="_window" parentCard="" /> : <div data-pihanga-waiting="">Connecting…</div>}
      {status !== "open" && hasWindow && (
        <div
          data-pihanga-status={status}
          style={{ position: "fixed", bottom: 8, right: 8, padding: "2px 8px", fontSize: 12, borderRadius: 4, background: "#fde68a", color: "#78350f", zIndex: 9999 }}
        >
          {status === "connecting" ? "reconnecting…" : "offline"}
        </div>
      )}
      {extras}
    </>
  );
}

export function startRemote(opts: StartRemoteOpts = {}): { store: RemoteStore; transport: Transport } {
  const url = opts.url ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  const transport = new Transport({ url, log: opts.log });
  const store = createStore(routeFromLocation(), [transportMiddleware(transport)]);
  window.addEventListener("popstate", () => store.dispatch({ type: A.ROUTE, route: routeFromLocation() }));
  // Handy for debugging and for backends that want to check what the bundle supports.
  (window as unknown as Record<string, unknown>).__pihanga = { store, transport, manifest };
  transport.attach(store);
  ReactDOM.createRoot(opts.root ?? document.getElementById("root")!).render(
    <React.StrictMode>
      <Provider store={store}>
        <Root extras={opts.extras} />
      </Provider>
    </React.StrictMode>,
  );
  return { store, transport };
}
