/** Public API of the lean runtime (for custom bundles). */
export { startRemote, type StartRemoteOpts } from "./start";
export { Card, cls_f } from "./card";
export { cardTypes, resolveCardType, manifest, frameworkPrefixes } from "./registry";
export { applyJsonPatch, parsePointer, PatchError } from "./patch";
export * from "./protocol";
