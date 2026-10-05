// Node module hooks used by extract-card-schemas.mjs to import compiled card
// modules outside a bundler: core → recording stub, CSS → empty module.
const STUB = new URL("./core-recorder.mjs", import.meta.url).href;
export async function resolve(spec, ctx, next) {
  if (spec === "@pihanga2/core" || spec.startsWith("@pihanga2/core/")) return { url: STUB, shortCircuit: true };
  if (spec.endsWith(".css")) return { url: "data:text/javascript,export default {}", shortCircuit: true };
  return next(spec, ctx);
}
