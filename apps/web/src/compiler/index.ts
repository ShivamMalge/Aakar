// Public surface of the deterministic SceneSpec compiler (task 1.1).
export { buildGeometry, TESSELLATION } from "./geometry";
export type { Geometry, GeometryType } from "./geometry";
export { compile } from "./compile";
export {
  DEFAULT_FOV,
  FIT_MARGIN,
  boundingSphere,
  defaultCutaway,
  fitDistance,
  frameScene,
  isShelled,
} from "./camera";
export type { Framing } from "./camera";
export {
  CONTAINMENT_THRESHOLD,
  SURFACE_VOLUME_RATIO,
  SURROUNDS_THRESHOLD,
  analyseContainment,
  classify,
  containmentWarnings,
  fractionInside,
  ownWorldBox,
} from "./containment";
export type { CompileWarning, ContainmentReport, ParentRelation } from "./containment";
export type { CompiledPart, CompiledScene, CompileResult } from "./compile";
// The referential constraints are the shared contract (ruling A): they live in
// packages/scenespec and are implemented once per stack. Re-exported here so compiler
// callers have one import site.
export { validateReferential } from "@scenespec/referential";
export type { ReferentialCode, ReferentialError } from "@scenespec/referential";
export { applyExplode, planExplode } from "./explode";
export type { ExplodeMode, ExplodePlan } from "./explode";
export { applyClipping, clipPlaneFor } from "./cutaway";
