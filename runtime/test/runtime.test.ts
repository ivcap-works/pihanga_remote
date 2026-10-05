import { describe, expect, it } from "vitest";
import { applyJsonPatch, parsePointer, PatchError } from "../src/patch";
import { A, initialState, rootReducer, type RemoteState } from "../src/store";

const base = () => ({
  page: { cardType: "shad/typography", text: "hi" },
  "page/main": { cardType: "pi/stack", content: ["a", "b", "c"] },
  cars: { cardType: "shad/data-table", rows: [{ id: 1 }, { id: 2 }] },
});

describe("parsePointer", () => {
  it("unescapes ~1 and ~0", () => {
    expect(parsePointer("/page~1main/x~0y")).toEqual(["page/main", "x~y"]);
    expect(parsePointer("")).toEqual([]);
  });
});

describe("applyJsonPatch", () => {
  it("add/replace/remove with structural sharing", () => {
    const b = base();
    const n = applyJsonPatch(b, [
      { op: "replace", path: "/page/text", value: "ho" },
      { op: "add", path: "/page~1main/content/-", value: "d" },
      { op: "remove", path: "/page~1main/content/0" },
    ]);
    expect(n.page.text).toBe("ho");
    expect(n["page/main"].content).toEqual(["b", "c", "d"]);
    expect(n.cars).toBe(b.cars); // untouched card keeps identity → no re-render
    expect(b.page.text).toBe("hi"); // base not mutated
  });

  it("supports move and copy (emitted by python jsonpatch)", () => {
    const n = applyJsonPatch(base(), [
      { op: "move", from: "/page~1main/content/2", path: "/page~1main/content/0" },
      { op: "copy", from: "/page", path: "/page2" },
    ]);
    expect(n["page/main"].content).toEqual(["c", "a", "b"]);
    expect((n as Record<string, unknown>).page2).toEqual({ cardType: "shad/typography", text: "hi" });
  });

  it("move of a whole card", () => {
    const n = applyJsonPatch(base() as Record<string, unknown>, [{ op: "move", from: "/page", path: "/home" }]);
    expect(n.page).toBeUndefined();
    expect(n.home).toEqual({ cardType: "shad/typography", text: "hi" });
  });

  it("test op and failures throw PatchError", () => {
    expect(() => applyJsonPatch(base(), [{ op: "test", path: "/page/text", value: "nope" }])).toThrow(PatchError);
    expect(() => applyJsonPatch(base(), [{ op: "replace", path: "/nope/x", value: 1 }])).toThrow(PatchError);
    expect(() => applyJsonPatch(base(), [{ op: "remove", path: "/cars/rows/5" }])).toThrow(PatchError);
  });

  it("root replace", () => {
    expect(applyJsonPatch(base(), [{ op: "replace", path: "", value: { x: { cardType: "t" } } }])).toEqual({
      x: { cardType: "t" },
    });
  });
});

describe("rootReducer", () => {
  const route = { path: [], query: {} };
  const snap = (s: RemoteState) =>
    rootReducer(s, { type: A.SNAPSHOT, version: 3, cards: base(), ack: 0 } as never);

  it("applies patches in order and flags version gaps", () => {
    let s = snap(initialState(route));
    s = rootReducer(s, { type: A.PATCH, base: 3, version: 4, ops: [{ op: "replace", path: "/page/text", value: "x" }] } as never);
    expect(s.remote.version).toBe(4);
    expect(s.cards.page.text).toBe("x");
    const s2 = rootReducer(s, { type: A.PATCH, base: 7, version: 8, ops: [] } as never);
    expect(s2.remote.needResync).toMatch(/version gap/);
    expect(s2.cards).toBe(s.cards);
  });

  it("failed patch leaves cards untouched and requests resync", () => {
    const s = snap(initialState(route));
    const s2 = rootReducer(s, { type: A.PATCH, base: 3, version: 4, ops: [{ op: "remove", path: "/zzz" }] } as never);
    expect(s2.cards).toBe(s.cards);
    expect(s2.remote.version).toBe(3);
    expect(s2.remote.needResync).toMatch(/patch failed/);
  });

  it("optimistic overlay is dropped once acknowledged", () => {
    let s = snap(initialState(route));
    s = rootReducer(s, { type: A.ECHO, card: "page", props: { text: "ab" }, seq: 5 } as never);
    s = rootReducer(s, { type: A.ECHO, card: "page", props: { text: "abc" }, seq: 6 } as never);
    expect(s.overlay.page.text).toEqual({ value: "abc", seq: 6 });
    // backend has processed seq 5 only → overlay (seq 6) must survive
    s = rootReducer(s, { type: A.PATCH, base: 3, version: 4, ops: [{ op: "replace", path: "/page/text", value: "ab" }], ack: 5 } as never);
    expect(s.overlay.page.text.value).toBe("abc");
    s = rootReducer(s, { type: A.PATCH, base: 4, version: 5, ops: [{ op: "replace", path: "/page/text", value: "abc" }], ack: 6 } as never);
    expect(s.overlay.page).toBeUndefined();
  });
});
