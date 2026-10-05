/**
 * Replacement for the CommonJS `use-sync-external-store/shim` package
 * (pulled in by @radix-ui/react-use-is-hydrated). The shim does
 * `require("react")`, which cannot work once React is an import-map external
 * in an ES module. React >= 18 has the hook built in, so re-export it.
 */
export { useSyncExternalStore } from "react";
