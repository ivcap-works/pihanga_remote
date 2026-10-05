#!/usr/bin/env node
/**
 * Assemble the "script tag" deployment: a generic index.html plus versioned
 * package folders laid out like a CDN (/pkg/<name>@<version>/...).
 *
 *   node browser/assemble.mjs <path-to-pihanga-shadcn-checkout> [outDir]
 *
 * Expects:  runtime/dist-browser/runtime   (npx vite build -c vite.runtime.config.ts)
 *           <shadcn>/dist-browser          (npx vite build -c vite.browser.config.ts)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const shadcnDir = path.resolve(process.argv[2] ?? path.join(root, "../pihanga-shadcn"));
const out = path.resolve(process.argv[3] ?? path.join(root, "backend/pihanga_remote/static_cdn"));

const runtimePkg = JSON.parse(fs.readFileSync(path.join(root, "runtime/package.json"), "utf8"));
const shadcnPkg = JSON.parse(fs.readFileSync(path.join(shadcnDir, "package.json"), "utf8"));
const RUNTIME_VERSION = "0.1.0"; // keep in sync with index.html's import map
if (runtimePkg.version !== RUNTIME_VERSION) console.warn(`runtime/package.json is ${runtimePkg.version}, import map says ${RUNTIME_VERSION}`);

const copy = (src, dst) => {
  if (!fs.existsSync(src)) throw new Error(`missing ${src} – build it first`);
  fs.cpSync(src, dst, { recursive: true });
};
fs.rmSync(out, { recursive: true, force: true });
copy(path.join(root, "runtime/dist-browser/runtime"), path.join(out, `pkg/@pihanga2/runtime@${RUNTIME_VERSION}`));
copy(path.join(shadcnDir, "dist-browser"), path.join(out, `pkg/@pihanga2/shadcn@${shadcnPkg.version}`));
copy(path.join(here, "acme-cards"), path.join(out, "pkg/acme-cards@0.1.0"));
fs.writeFileSync(
  path.join(out, "index.html"),
  fs.readFileSync(path.join(here, "index.html"), "utf8").replaceAll("SHADCN_VERSION", shadcnPkg.version),
);
console.log(`assembled ${out} (runtime ${RUNTIME_VERSION}, shadcn ${shadcnPkg.version})`);
