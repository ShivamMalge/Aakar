// Deterministic, bounds-derived framing (ruling 9).
//
// The stress fixture found this: the neuron's first `camera_hint` was authored in the
// shape of a 1-unit topic and cropped a 6-unit assembly at both ends. Every golden spec
// happens to be about one unit across, so an authored distance looked fine right up to
// the first topic that was not.
//
// THE RULE
//
//   1. Fit the scene's bounding SPHERE, not its box. A box's fit depends on which way the
//      scene is turned, so orbiting would push the model out of frame; a sphere is
//      rotation-invariant and the framing holds at every angle.
//   2. The camera DIRECTION comes from `camera_hint` when present, defaulting to a 3/4
//      view. The DISTANCE is always derived. That keeps the authored viewpoint — which is
//      a real editorial choice — while removing the one number an author cannot get right
//      without knowing the final bounds.
//   3. `look_at` is the bounding-sphere centre, not the origin. A neuron's mass sits well
//      off the origin, and aiming at the origin wastes half the frame.
//   4. The fit accounts for aspect ratio: at 1280x900 the vertical FOV is the binding
//      constraint, but a portrait viewport makes it horizontal, and ignoring that crops
//      on phones (Phase 4's mobile QA).
//
// CUTAWAY DEFAULT
//
// A "shelled" topic — one whose largest part is opaque and encloses most of the others —
// shows nothing but that shell from outside, so it defaults to cutaway. Measured from the
// geometry and the material rather than guessed from the topic name: see `isShelled`.
import * as THREE from "three";

import type { SceneSpec } from "../scenespec";

import { fractionInside, ownWorldBox } from "./containment";

/** Breathing room around the fitted sphere. */
export const FIT_MARGIN = 1.15;
/** Vertical field of view, degrees. Matches the Canvas. */
export const DEFAULT_FOV = 45;
/** A part this fraction inside the largest part counts as enclosed by it. */
const ENCLOSED_THRESHOLD = 0.9;
/** This fraction of the other parts enclosed makes a topic "shelled". */
const SHELLED_FRACTION = 0.5;
/**
 * A shell only hides things if you cannot see through it.
 *
 * Measured, not assumed: with cutaway forced on, `animal_cell` places 7 labels of 13 and
 * `human_eye` places 12 of 12; with it forced off, `animal_cell` places 13 and `human_eye`
 * places 1. The cell's membrane is at 0.18 opacity, so its exterior view already shows
 * every organelle, and cutting it away costs six labels while revealing nothing. An eye's
 * sclera at 0.97 hides everything, so it must be cut.
 */
const SHELL_OPACITY = 0.85;

const DEFAULT_DIRECTION = new THREE.Vector3(3, 2, 4).normalize();

export type Framing = {
  position: THREE.Vector3;
  target: THREE.Vector3;
  /** Radius of the fitted bounding sphere — useful for near/far planes. */
  radius: number;
};

/** World-space bounding sphere over every part's own geometry. */
export function boundingSphere(meshes: Iterable<THREE.Mesh>): THREE.Sphere {
  const box = new THREE.Box3();
  let any = false;
  for (const mesh of meshes) {
    box.union(ownWorldBox(mesh));
    any = true;
  }
  if (!any || box.isEmpty()) return new THREE.Sphere(new THREE.Vector3(), 1);

  const centre = box.getCenter(new THREE.Vector3());
  // The box's half-diagonal bounds every corner, so it bounds every vertex.
  const radius = box.getSize(new THREE.Vector3()).length() / 2;
  return new THREE.Sphere(centre, Math.max(radius, 1e-6));
}

/**
 * Distance at which a sphere of `radius` exactly fills the frustum.
 *
 * The binding half-angle is the smaller of vertical and horizontal, so a portrait
 * viewport fits on width and a landscape one on height.
 */
export function fitDistance(radius: number, fovDegrees: number, aspect: number): number {
  const vertical = (fovDegrees * Math.PI) / 180 / 2;
  const horizontal = Math.atan(Math.tan(vertical) * aspect);
  const binding = Math.min(vertical, horizontal);
  return (radius / Math.sin(binding)) * FIT_MARGIN;
}

/**
 * Where to put the camera for this spec.
 *
 * `angle` is a quarter-turn index about Y, so gate captures and the Phase 3 critic can
 * ask for reproducible viewpoints.
 */
export function frameScene(
  spec: SceneSpec,
  meshes: Iterable<THREE.Mesh>,
  { angle = 0, aspect = 1280 / 900, fov = DEFAULT_FOV } = {},
): Framing {
  const sphere = boundingSphere(meshes);

  const hint = spec.camera_hint?.position;
  const direction =
    hint === undefined
      ? DEFAULT_DIRECTION.clone()
      : new THREE.Vector3(hint[0], hint[1], hint[2]);

  // A hint pointing at the origin carries no direction; fall back rather than divide by
  // zero and put the camera inside the model.
  if (direction.lengthSq() < 1e-9) direction.copy(DEFAULT_DIRECTION);
  direction.normalize().applyAxisAngle(new THREE.Vector3(0, 1, 0), (angle * Math.PI) / 2);

  const distance = fitDistance(sphere.radius, fov, aspect);
  return {
    position: sphere.center.clone().addScaledVector(direction, distance),
    target: sphere.center.clone(),
    radius: sphere.radius,
  };
}

/**
 * Does the largest part enclose most of the others?
 *
 * Earth's layers, an eyeball and a cell all read as a featureless shell from outside, so
 * they should open in cutaway. A neuron does not — its parts are laid out along an axis,
 * and cutting it in half would hide the arborisation the topic is about.
 *
 * Measured, not guessed: no topic-name heuristics, and it stays correct for topics that
 * do not exist yet.
 */
export function isShelled(spec: SceneSpec, meshes: ReadonlyMap<string, THREE.Mesh>): boolean {
  if (spec.parts.length < 2) return false;

  const partById = new Map(spec.parts.map((part) => [part.id, part]));
  let largestId: string | undefined;
  let largestVolume = -1;

  for (const [id, mesh] of meshes) {
    const size = ownWorldBox(mesh).getSize(new THREE.Vector3());
    const volume = size.x * size.y * size.z;
    if (volume > largestVolume) {
      largestVolume = volume;
      largestId = id;
    }
  }

  const shell = largestId === undefined ? undefined : meshes.get(largestId);
  const shellPart = largestId === undefined ? undefined : partById.get(largestId);
  if (shell === undefined || shellPart === undefined) return false;

  // A see-through shell is not a shell for this purpose.
  if ((shellPart.material.opacity ?? 1) <= SHELL_OPACITY) return false;

  let enclosed = 0;
  let considered = 0;
  for (const [id, mesh] of meshes) {
    if (id === largestId) continue;
    considered += 1;
    if (fractionInside(mesh, shell, shellPart.geometry) >= ENCLOSED_THRESHOLD) enclosed += 1;
  }

  return considered > 0 && enclosed / considered >= SHELLED_FRACTION;
}

/** The cutaway state a topic should open in, absent an explicit request. */
export function defaultCutaway(
  spec: SceneSpec,
  meshes: ReadonlyMap<string, THREE.Mesh>,
): boolean {
  // A spec that switches cutaway off is taken at its word.
  if (spec.cutaway?.enabled === false) return false;
  return isShelled(spec, meshes);
}
