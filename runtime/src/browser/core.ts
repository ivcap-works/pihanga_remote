/**
 * "@pihanga2/core" as seen by card libraries loaded from <script> tags.
 * Same surface as the bundler shim (src/core-shim.ts) plus the bootstrap API.
 */
export * from "../core-shim";
export { startRemote, type StartRemoteOpts } from "../start";
export { cardTypes, manifest, resolveCardType, frameworkPrefixes } from "../registry";
export { cls_f } from "../card";
export const RUNTIME = { name: "@pihanga2/remote-runtime", version: "0.1.0" };
