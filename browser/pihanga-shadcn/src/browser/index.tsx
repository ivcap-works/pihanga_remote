/**
 * Browser ("script tag") entry of @pihanga2/shadcn.
 *
 * Loading this ES module registers every core card with the shared
 * `@pihanga2/core` provided by the page's import map. It bundles all
 * third-party dependencies (Radix, lucide, sonner, vaul, …) but NOT
 * react / react-dom / react/jsx-runtime / @pihanga2/core — those must be the
 * single shared copies, otherwise hooks break and there are two registries.
 *
 * Build: npx vite build -c vite.browser.config.ts  → dist-browser/
 */
import "./browser.css";
import "virtual:pihanga-core-cards"; // side-effect imports of scripts/core-cards.json
import "./icons";
import * as React from "react";
import { Toaster } from "sonner";
import { registerCardComponent } from "@pihanga2/core";
import { Component as Framework } from "@/cards/framework/framework.component";

// The toast card calls sonner's `toast()`, which needs <Toaster/> mounted
// somewhere. In the npm setup the *app* renders it (src/app.root.tsx); a
// generic page has no app code, so the framework card has to provide it.
// RECOMMENDED upstream fix: render <Toaster/> inside framework.component.tsx
// and drop this override.
function FrameworkWithToaster(props: React.ComponentProps<typeof Framework>) {
  return (
    <>
      <Framework {...props} />
      <Toaster />
    </>
  );
}
registerCardComponent({ name: "shad/framework", component: FrameworkWithToaster });

export const LIBRARY = { name: "@pihanga2/shadcn", version: __PKG_VERSION__ };
