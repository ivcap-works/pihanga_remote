#!/usr/bin/env node
/**
 * Extract a machine-readable card catalogue (JSON Schema) from a compiled
 * Pihanga card library, e.g. @pihanga2/shadcn.
 *
 *   node tools/extract-card-schemas.mjs [package] [outFile]
 *
 * Output (one file):
 *   {
 *     library, version, generatedBy,
 *     cards: {
 *       "<cardType>": {
 *         declaration: "Button", module: "cards/button",
 *         props:  <JSON Schema of the card's Props type>,
 *         events: { "onClicked": { actionType: "pi/button/clicked", payload: <JSON Schema> } }
 *       }
 *     },
 *     definitions: { ... shared $defs ... },
 *     problems: [ ... anything that could not be extracted ... ]
 *   }
 *
 * How it works (no cooperation from the card library needed):
 *  1. Import every card module in Node with a recording stand-in for
 *     @pihanga2/core → which declaration function creates which cardType, and
 *     which event names map to which action types.
 *  2. Read the library's .d.ts files with the TypeScript compiler API → for
 *     each declaration `X: (p: PiMapProps<Props, S, Events>) => PiCardDef`
 *     take the `Props` and `Events` type expressions.
 *  3. Run ts-json-schema-generator over a scratch copy of the .d.ts tree in
 *     which @pihanga2/core is replaced by a tiny stub (PiCardRef = string).
 *
 * The recommended long-term setup is for card libraries to run an equivalent
 * step in their own build and publish `cards.schema.json` with the package.
 */
import { register } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { createGenerator } from "ts-json-schema-generator";

register("./node-hooks.mjs", import.meta.url);
globalThis.window ??= globalThis; // some card modules touch `window` at import time

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgName = process.argv[2] ?? "@pihanga2/shadcn";
const outFile = path.resolve(process.argv[3] ?? path.join(here, "../../schemas/shadcn.cards.json"));
const pkgDir = path.join(here, "../node_modules", pkgName);
const pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, "package.json"), "utf8"));
const problems = [];

// ----------------------------------------------------------------------------- 1. runtime facts
const decls = {}; // exportName -> { module, cardType }
const cardModules = Object.keys(pkg.exports)
  .filter((k) => k.startsWith("./cards/") && !/\/(types|icons)$/.test(k))
  .map((k) => k.slice(2));

async function collect(mod, spec) {
  const m = await import(spec);
  for (const [n, v] of Object.entries(m)) if (typeof v === "function" && v.__cardType) decls[n] ??= { module: mod, cardType: v.__cardType };
}
for (const mod of cardModules) {
  try {
    await collect(mod, `${pkgName}/${mod}`);
  } catch (e) {
    // Fall back to the side-effect-free *.types.js files of that card.
    const dir = path.join(pkgDir, mod);
    const typeFiles = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => /\.types?\.js$/.test(f)) : [];
    if (typeFiles.length === 0) problems.push({ module: mod, problem: `cannot import: ${String(e).slice(0, 160)}` });
    for (const f of typeFiles) {
      try {
        await collect(mod, path.join(dir, f));
      } catch (e2) {
        problems.push({ module: mod, problem: `cannot import ${f}: ${String(e2).slice(0, 160)}` });
      }
    }
  }
}
const recorded = globalThis.__piRecorded;

// ----------------------------------------------------------------------------- 2. d.ts analysis
const work = path.join(here, ".work");
fs.rmSync(work, { recursive: true, force: true });
const libCopy = path.join(work, "lib");
fs.cpSync(pkgDir, libCopy, { recursive: true, filter: (s) => fs.statSync(s).isDirectory() || s.endsWith(".d.ts") || s.endsWith("package.json") });

// Normalise the .d.ts copies for ts-json-schema-generator:
//  - React types (ElementType, CSSProperties, ReactNode, ...) mean nothing to a
//    JSON backend and trip the generator → opaque `ReactValue` alias;
//  - inline `import('mod').Name` type nodes are not supported by the generator
//    → hoist them into regular `import type` statements.
for (const f of fs.readdirSync(libCopy, { recursive: true })) {
  if (!String(f).endsWith(".d.ts")) continue;
  const p = path.join(libCopy, String(f));
  const src = fs.readFileSync(p, "utf8");
  let out = src.replace(/\bReact\.[A-Za-z]+(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?/g, "import('@pihanga2/core').ReactValue");
  const imports = new Map(); // local alias -> [module, name]
  out = out.replace(/import\((['"])([^'"]+)\1\)\.([A-Za-z_$][\w$]*)/g, (_m, _q, mod, name) => {
    const alias = `__imp_${name}_${mod.replace(/[^\w]/g, "_")}`;
    imports.set(alias, [mod, name]);
    return alias;
  });
  if (imports.size) {
    const lines = [...imports].map(([a, [m, n]]) => `import type { ${n} as ${a} } from '${m}';`);
    out = lines.join("\n") + "\n" + out;
  }
  if (out !== src) fs.writeFileSync(p, out);
}

// @pihanga2/core stub: only what the .d.ts files reference. PiCardRef is a plain
// string — in the remote runtime child cards are always referenced by name.
const coreStub = path.join(work, "node_modules/@pihanga2/core");
fs.mkdirSync(coreStub, { recursive: true });
const stub = `
/** Name of another card (resolved by the backend). */
export type PiCardRef = string;
export type PiCardName = string;
export type PiCardDef = { cardType: string; [k: string]: unknown };
export type ReduxState = { [k: string]: unknown };
export type ReduxAction = { type: string };
export type DispatchF = (a: ReduxAction) => void;
export type ReduceF<S, A> = (s: S, a: A) => void;
export type PiMapProps<P, S = unknown, E = {}> = P;
export type PiCardProps<P, E = {}> = P & { cardName: string };
export type PiRegisterMinimal = unknown;
export type WindowProps = { page: PiCardRef; framework?: string; theme?: "light" | "dark" | "system" };
export type PiMetaProps<P> = P;
export type PiMetaResolveCtx = unknown;
export type PiRegisterMetaCard = unknown;
export type RegisterCardF = unknown;
/** A React-only value (element type, CSS properties, node); free-form JSON here. */
export type ReactValue = unknown;
`;
fs.writeFileSync(path.join(coreStub, "package.json"), JSON.stringify({ name: "@pihanga2/core", types: "index.d.ts" }));
fs.writeFileSync(path.join(coreStub, "index.d.ts"), stub);
fs.writeFileSync(path.join(coreStub, "types.d.ts"), `export * from "./index";`);
for (const dep of ["@types/react", "@types/react-dom", "csstype"]) {
  const src = path.join(here, "../node_modules", dep);
  if (fs.existsSync(src)) {
    fs.mkdirSync(path.dirname(path.join(work, "node_modules", dep)), { recursive: true });
    fs.symlinkSync(src, path.join(work, "node_modules", dep));
  }
}

const program = ts.createProgram(
  cardModules.map((m) => path.join(libCopy, m, "index.d.ts")).filter((f) => fs.existsSync(f)),
  { skipLibCheck: true, noEmit: true },
);
const checker = program.getTypeChecker();

/** exportName -> { file, propsText, eventsText } */
const typeInfo = {};
for (const mod of cardModules) {
  const idx = program.getSourceFile(path.join(libCopy, mod, "index.d.ts"));
  if (!idx) continue;
  const modSym = checker.getSymbolAtLocation(idx);
  for (const ex of checker.getExportsOfModule(modSym)) {
    if (!decls[ex.name] || typeInfo[ex.name]) continue;
    const sym = ex.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(ex) : ex;
    const d = sym.declarations?.[0];
    if (!d || !ts.isVariableDeclaration(d) || !d.type || !ts.isFunctionTypeNode(d.type)) continue;
    const pt = d.type.parameters[0]?.type;
    const args = pt && (ts.isImportTypeNode(pt) || ts.isTypeReferenceNode(pt)) ? pt.typeArguments : undefined;
    if (!args || args.length < 1) {
      problems.push({ declaration: ex.name, problem: "declaration type is not PiMapProps<Props, S, Events>" });
      continue;
    }
    const sf = d.getSourceFile();
    const tp = d.type.typeParameters?.map((p) => p.name.text) ?? [];
    const clean = (n) => {
      let t = n.getText(sf);
      for (const p of tp) t = t.replace(new RegExp(`\\b${p}\\b`, "g"), "unknown");
      return t;
    };
    typeInfo[ex.name] = { file: sf.fileName, propsText: clean(args[0]), eventsText: args[2] ? clean(args[2]) : "{}" };
  }
}

// ----------------------------------------------------------------------------- 3. JSON Schema
const byFile = {};
for (const [n, t] of Object.entries(typeInfo)) (byFile[t.file] ??= []).push(n);
const entryLines = [];
for (const [file, names] of Object.entries(byFile)) {
  const extra = names.map((n) => `export type __PiProps__${n} = ${typeInfo[n].propsText};\nexport type __PiEvents__${n} = ${typeInfo[n].eventsText};`);
  fs.appendFileSync(file, "\n" + extra.join("\n") + "\n");
  const rel = "./" + path.relative(work, file).replace(/\.d\.ts$/, "");
  entryLines.push(`export type { ${names.flatMap((n) => [`__PiProps__${n}`, `__PiEvents__${n}`]).join(", ")} } from "${rel}";`);
}
const entry = path.join(work, "entry.ts");
fs.writeFileSync(entry, entryLines.join("\n") + "\n");
fs.writeFileSync(
  path.join(work, "tsconfig.json"),
  JSON.stringify({ compilerOptions: { strict: true, skipLibCheck: true, moduleResolution: "node", jsx: "react-jsx", baseUrl: "." }, files: ["entry.ts"] }),
);

const gen = createGenerator({
  path: entry,
  tsconfig: path.join(work, "tsconfig.json"),
  type: "*",
  expose: "export",
  topRef: false,
  jsDoc: "extended",
  functions: "hide",
  skipTypeCheck: true,
  additionalProperties: true,
});

const definitions = {};
function hoist(schema, ctx) {
  // Move nested definitions into the shared pool; rename on (rare) conflicts.
  const defs = schema.definitions ?? {};
  delete schema.definitions;
  const renames = {};
  for (const [k, v] of Object.entries(defs)) {
    let name = k;
    if (definitions[name] && JSON.stringify(definitions[name]) !== JSON.stringify(v)) {
      name = `${k}__${ctx}`;
      renames[k] = name;
    }
    definitions[name] = v;
  }
  if (Object.keys(renames).length) {
    const s = JSON.stringify(schema).replace(/"#\/definitions\/([^"]+)"/g, (m, r) => {
      const d = decodeURIComponent(r);
      return renames[d] ? `"#/definitions/${encodeURIComponent(renames[d])}"` : m;
    });
    return JSON.parse(s);
  }
  return schema;
}

// React.* types (CSSProperties, ReactNode, ...) are not meaningful for a JSON
// backend: collapse them to "any JSON".
function simplify(schema) {
  return JSON.parse(
    JSON.stringify(schema, (_k, v) => {
      if (v && typeof v === "object" && typeof v.$ref === "string" && /#\/definitions\/(React\.|CSSProperties|csstype|Property\.|DataType\.|Globals)/.test(decodeURIComponent(v.$ref))) {
        return { description: "React/CSS value (free-form JSON)" };
      }
      return v;
    }),
  );
}

function deref(schema) {
  let s = schema;
  for (let i = 0; i < 10 && s && typeof s.$ref === "string"; i++) {
    s = definitions[decodeURIComponent(s.$ref.replace("#/definitions/", ""))];
  }
  return s;
}

const cards = {};
for (const [n, info] of Object.entries(decls)) {
  const card = { declaration: n, module: info.module, props: null, events: {} };
  const registered = recorded.cardTypes[info.cardType] ?? recorded.cardTypes[`shad/${info.cardType}`] ?? recorded.cardTypes[`pi/${info.cardType}`];
  const evMap = registered?.events ?? recorded.metaCards[info.cardType]?.events ?? {};
  if (recorded.metaCards[info.cardType]) card.metaCard = true;
  if (!registered && !card.metaCard) problems.push({ declaration: n, cardType: info.cardType, problem: "no registered component for this card type" });
  if (typeInfo[n]) {
    try {
      card.props = simplify(hoist(gen.createSchema(`__PiProps__${n}`), n));
    } catch (e) {
      problems.push({ declaration: n, problem: `props schema: ${String(e.message ?? e).split("\n")[0].slice(0, 200)}` });
    }
    let evSchema = null;
    try {
      evSchema = simplify(hoist(gen.createSchema(`__PiEvents__${n}`), n));
    } catch (e) {
      problems.push({ declaration: n, problem: `events schema: ${String(e.message ?? e).split("\n")[0].slice(0, 200)}` });
    }
    const evObj = deref(evSchema);
    for (const [ev, actionType] of Object.entries(evMap)) {
      card.events[ev] = { actionType, payload: evObj?.properties?.[ev] ?? {} };
    }
  } else {
    problems.push({ declaration: n, problem: "no typed declaration found in .d.ts" });
    for (const [ev, actionType] of Object.entries(evMap)) card.events[ev] = { actionType, payload: {} };
  }
  // Canonical (fully qualified) card type as registered in the bundle.
  const canonical = registered ? Object.keys(recorded.cardTypes).find((k) => recorded.cardTypes[k] === registered) : info.cardType;
  if (cards[canonical]) {
    card.aliasOf = cards[canonical].declaration; // several declaration functions for one type
    cards[canonical].aliases = [...(cards[canonical].aliases ?? []), n];
    continue;
  }
  cards[canonical] = card;
}

// ts-json-schema-generator names generic instantiations with internal ids
// (e.g. "BoxProps<object-3877...>"). Give them stable, readable names.
function tidyNames(cardsObj, defs) {
  const rename = {};
  const taken = new Set(Object.keys(defs).filter((k) => !k.includes("<")));
  for (const k of Object.keys(defs)) {
    if (!k.includes("<")) continue;
    const base = k.slice(0, k.indexOf("<"));
    let name = base;
    for (let i = 2; taken.has(name); i++) {
      if (JSON.stringify(defs[name]) === JSON.stringify(defs[k])) break;
      name = `${base}_${i}`;
    }
    taken.add(name);
    rename[k] = name;
  }
  const fix = (o) =>
    JSON.parse(
      JSON.stringify(o).replace(/"#\/definitions\/([^"]+)"/g, (m, r) => {
        const d = decodeURIComponent(r);
        return rename[d] ? `"#/definitions/${encodeURIComponent(rename[d])}"` : m;
      }),
    );
  const newDefs = {};
  for (const [k, v] of Object.entries(defs)) newDefs[rename[k] ?? k] = v;
  return [fix(cardsObj), fix(newDefs)];
}
const [tidyCards, tidyDefs] = tidyNames(cards, definitions);

// Keep only definitions reachable from the cards.
function prune(cardsObj, defs) {
  const keep = new Set();
  const visit = (o) => {
    JSON.stringify(o, (_k, v) => {
      if (v && typeof v === "object" && typeof v.$ref === "string") {
        const n = decodeURIComponent(v.$ref.replace("#/definitions/", ""));
        if (!keep.has(n) && defs[n]) {
          keep.add(n);
          visit(defs[n]);
        }
      }
      return v;
    });
  };
  visit(cardsObj);
  return Object.fromEntries(Object.entries(defs).filter(([k]) => keep.has(k)).sort(([a], [b]) => a.localeCompare(b)));
}
const finalCards = simplify(tidyCards);
const finalDefs = prune(finalCards, simplify(tidyDefs));

const out = {
  library: pkgName,
  version: pkg.version,
  generatedBy: "pihanga-remote/tools/extract-card-schemas.mjs",
  cards: Object.fromEntries(Object.entries(finalCards).sort(([a], [b]) => a.localeCompare(b))),
  definitions: finalDefs,
  problems,
};
fs.mkdirSync(path.dirname(outFile), { recursive: true });
fs.writeFileSync(outFile, JSON.stringify(out, null, 2));
console.log(`${Object.keys(cards).length} card types → ${outFile}`);
if (problems.length) console.log(`${problems.length} problem(s):\n` + problems.map((p) => "  - " + JSON.stringify(p)).join("\n"));
