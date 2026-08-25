// Exploded view (task 1.4). Deterministic, computed from the compiled scene — there is
// no schema field for it (spec §4).
//
// G-10 is the open question this file exists to answer: exploding every part from one
// global centroid pulls children away from their parents. Both candidate readings are
// implemented so the call can be made in the running viewer, which is what G-10 asks.
import * as THREE from "three";

import type { CompiledScene } from "./compile";

export type ExplodeMode =
  /** Only root parts move; children ride along inside their parent. */
  | "top-level"
  /** Every part moves to its own radial offset, compensated so it is not displaced twice. */
  | "per-part";

export type ExplodePlan = {
  readonly mode: ExplodeMode;
  /** World-space displacement at factor = 1, per part id. */
  readonly offsets: ReadonlyMap<string, THREE.Vector3>;
};

/** Direction used when a part sits exactly on the centroid (concentric shells). */
const CONCENTRIC_AXIS = new THREE.Vector3(0, 1, 0);
/** Gap between successive shells in the concentric stack, in assembly radii. */
const CONCENTRIC_SPACING = 0.55;
const DEGENERATE = 1e-6;

/**
 * Concentric topics — Earth's layers being the canonical one — put every part at the
 * assembly centre, so "radially from the centroid" has no direction to offer. Those
 * parts are instead stacked along one axis, largest shell first, which is the reading
 * of an exploded view that survives nesting.
 */
function concentricRanks(scene: CompiledScene, ids: readonly string[]): Map<string, number> {
  const ordered = [...ids].sort((a, b) => {
    const ra = scene.parts.get(a)?.restRadius ?? 0;
    const rb = scene.parts.get(b)?.restRadius ?? 0;
    if (rb !== ra) return rb - ra;
    return a < b ? -1 : 1; // stable, id-ordered: determinism (D1)
  });
  return new Map(ordered.map((id, i) => [id, i]));
}

export function planExplode(scene: CompiledScene, mode: ExplodeMode): ExplodePlan {
  const movers =
    mode === "top-level"
      ? scene.order.filter((id) => scene.parts.get(id)?.part.parent_id === undefined)
      : [...scene.order];

  const radial = new Map<string, THREE.Vector3>();
  const concentric: string[] = [];

  for (const id of movers) {
    const compiled = scene.parts.get(id);
    if (compiled === undefined) continue;
    const dir = compiled.restWorldPosition.clone().sub(scene.centroid);
    if (dir.lengthSq() <= DEGENERATE) concentric.push(id);
    else radial.set(id, dir.normalize().multiplyScalar(scene.radius));
  }

  const ranks = concentricRanks(scene, concentric);
  const offsets = new Map<string, THREE.Vector3>(radial);
  // Spread the stack symmetrically about the centroid rather than pushing it all one
  // way: a one-directional stack walks the assembly out of frame, and the further a
  // topic gets from concentric the worse it looks. Centring keeps the camera hint
  // usable at any explode factor.
  const middle = (ranks.size - 1) / 2;
  for (const [id, rank] of ranks) {
    offsets.set(
      id,
      CONCENTRIC_AXIS.clone().multiplyScalar(scene.radius * (rank - middle) * CONCENTRIC_SPACING),
    );
  }

  return { mode, offsets };
}

/**
 * Move parts to `factor` along the plan. factor = 0 restores the spec's own transforms
 * exactly, so the slider is lossless in both directions.
 */
export function applyExplode(scene: CompiledScene, plan: ExplodePlan, factor: number): void {
  const zero = new THREE.Vector3();

  for (const id of scene.order) {
    const compiled = scene.parts.get(id);
    if (compiled === undefined) continue;

    const own = plan.offsets.get(id);
    if (own === undefined) {
      // No offset of its own — "top-level" mode's children. Staying put in local space
      // is what makes it ride along inside its parent; compensating here would cancel
      // the parent's movement instead.
      compiled.mesh.position.copy(compiled.basePosition);
      continue;
    }

    // Net world displacement should equal `own` — not `own` plus whatever the parent
    // already moved — so subtract the parent's share before converting to local space.
    const parentId = compiled.part.parent_id;
    const inherited = (parentId !== undefined ? plan.offsets.get(parentId) : undefined) ?? zero;

    const worldDelta = own.clone().sub(inherited).multiplyScalar(factor);

    const parentMesh = compiled.mesh.parent;
    if (parentMesh !== null && parentMesh !== scene.root) {
      // Rotate/scale the world delta into the parent's frame; translation is irrelevant
      // for a delta, so only the linear part of the inverse matters.
      const linear = new THREE.Matrix3().setFromMatrix4(
        new THREE.Matrix4().copy(parentMesh.matrixWorld).invert(),
      );
      worldDelta.applyMatrix3(linear);
    }

    compiled.mesh.position.copy(compiled.basePosition).add(worldDelta);
  }

  scene.root.updateMatrixWorld(true);
}
