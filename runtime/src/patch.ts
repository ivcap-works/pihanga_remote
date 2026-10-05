/**
 * Minimal RFC 6902 (JSON Patch) applier on top of Immer.
 *
 * Why not Immer's `applyPatches`? It only supports add/replace/remove, while
 * Python's `jsonpatch.make_patch` also emits `move` (and other producers may
 * emit `copy`/`test`). Applying ops on an Immer draft keeps structural sharing:
 * untouched cards keep their object identity, so only affected cards re-render.
 */
import { produce, current, isDraft, type Draft } from "immer";
import type { JsonPatchOp } from "./protocol";

export class PatchError extends Error {}

/** RFC 6901 JSON-Pointer → path segments ("" → []). */
export function parsePointer(pointer: string): string[] {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) throw new PatchError(`invalid JSON pointer '${pointer}'`);
  return pointer
    .slice(1)
    .split("/")
    .map((s) => s.replaceAll("~1", "/").replaceAll("~0", "~"));
}

type Container = Record<string, unknown> | unknown[];

function isContainer(v: unknown): v is Container {
  return typeof v === "object" && v !== null;
}

function arrayIndex(arr: unknown[], seg: string, allowEnd: boolean): number {
  if (seg === "-" && allowEnd) return arr.length;
  if (!/^(0|[1-9][0-9]*)$/.test(seg)) throw new PatchError(`invalid array index '${seg}'`);
  const i = Number(seg);
  const max = allowEnd ? arr.length : arr.length - 1;
  if (i > max) throw new PatchError(`array index ${i} out of bounds`);
  return i;
}

function parentOf(root: unknown, segs: string[]): [Container, string] {
  let node: unknown = root;
  for (let i = 0; i < segs.length - 1; i++) {
    const s = segs[i];
    if (Array.isArray(node)) node = node[arrayIndex(node, s, false)];
    else if (isContainer(node) && s in node) node = (node as Record<string, unknown>)[s];
    else throw new PatchError(`path segment '${s}' not found`);
  }
  if (!isContainer(node)) throw new PatchError(`parent of '/${segs.join("/")}' is not a container`);
  return [node, segs[segs.length - 1]];
}

function getAt(root: unknown, segs: string[]): unknown {
  if (segs.length === 0) return root;
  const [p, k] = parentOf(root, segs);
  if (Array.isArray(p)) return p[arrayIndex(p, k, false)];
  if (!(k in p)) throw new PatchError(`'/${segs.join("/")}' not found`);
  return (p as Record<string, unknown>)[k];
}

function plain(v: unknown): unknown {
  // Detach a value read from the draft so it can be re-inserted elsewhere.
  const c: unknown = isDraft(v) ? current(v as object) : v;
  return c === undefined ? c : structuredClone(c);
}

function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function applyOne(draft: Record<string, unknown>, op: JsonPatchOp): void {
  const segs = parsePointer(op.path);
  const add = (s: string[], value: unknown) => {
    if (s.length === 0) throw new PatchError("root add/replace must be handled outside the draft");
    const [p, k] = parentOf(draft, s);
    if (Array.isArray(p)) p.splice(arrayIndex(p, k, true), 0, value);
    else (p as Record<string, unknown>)[k] = value;
  };
  const remove = (s: string[]) => {
    if (s.length === 0) throw new PatchError("cannot remove the root");
    const [p, k] = parentOf(draft, s);
    if (Array.isArray(p)) p.splice(arrayIndex(p, k, false), 1);
    else if (k in p) delete (p as Record<string, unknown>)[k];
    else throw new PatchError(`'${op.path}' not found`);
  };
  switch (op.op) {
    case "add":
      add(segs, op.value);
      return;
    case "remove":
      remove(segs);
      return;
    case "replace": {
      getAt(draft, segs); // must exist
      const [p, k] = parentOf(draft, segs);
      if (Array.isArray(p)) p[arrayIndex(p, k, false)] = op.value;
      else (p as Record<string, unknown>)[k] = op.value;
      return;
    }
    case "move": {
      if (op.path === op.from) return;
      if (op.path.startsWith(op.from + "/")) throw new PatchError("cannot move into own child");
      const from = parsePointer(op.from);
      const v = plain(getAt(draft, from));
      remove(from);
      add(segs, v);
      return;
    }
    case "copy":
      add(segs, plain(getAt(draft, parsePointer(op.from))));
      return;
    case "test":
      if (!deepEqual(plain(getAt(draft, segs)), op.value)) throw new PatchError(`test failed at '${op.path}'`);
      return;
    default:
      throw new PatchError(`unsupported op '${(op as { op: string }).op}'`);
  }
}

/**
 * Apply `ops` to `base` and return the new (structurally shared) value.
 * Throws `PatchError` if any op fails; `base` itself is never mutated.
 */
export function applyJsonPatch<T extends Record<string, unknown>>(base: T, ops: JsonPatchOp[]): T {
  let state: T = base;
  let batch: JsonPatchOp[] = [];
  const flush = () => {
    if (batch.length === 0) return;
    const b = batch;
    batch = [];
    state = produce(state, (draft: Draft<T>) => {
      for (const op of b) applyOne(draft as Record<string, unknown>, op);
    });
  };
  for (const op of ops) {
    if (op.path === "" && (op.op === "add" || op.op === "replace")) {
      flush();
      state = op.value as T; // whole-document replacement
    } else {
      batch.push(op);
    }
  }
  flush();
  return state;
}
