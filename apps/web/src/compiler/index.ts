// Public surface of the deterministic SceneSpec compiler (task 1.1).
export { buildGeometry, TESSELLATION } from "./geometry";
export type { Geometry, GeometryType } from "./geometry";
export { compile } from "./compile";
export type { CompiledPart, CompiledScene, CompileResult } from "./compile";
export { validateGraph } from "./validate";
export type { SpecError } from "./validate";
export { applyExplode, planExplode } from "./explode";
export type { ExplodeMode, ExplodePlan } from "./explode";
export { applyClipping, clipPlaneFor } from "./cutaway";
