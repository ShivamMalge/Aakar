// Containment warnings (ruling A(d)).
//
// D-017 established that `parent_id` means "is contained by" — that is why the exploded
// view moves top-level parts only, and why a nucleolus must not leave its nucleus. But
// nothing checked that a spec's parenting actually reflects containment, and a spec that
// parents parts for convenience explodes wrongly with no diagnostic.
//
// This is a WARNING, not an error. Legitimate exceptions exist: a nuclear envelope
// surrounds its nucleus rather than sitting inside it, and an optic nerve is attached to
// an eyeball while extending well beyond it. So this informs the human curation gate
// (Rule 8) and the Phase 3 repair prompt; it never blocks.
import * as THREE from "three";

/** A child must have at least this much of its own volume inside its parent. */
export const CONTAINMENT_THRESHOLD = 0.9;

export type CompileWarning = {
  code: "parent_containment";
  partId: string;
  parentId: string;
  /** Fraction of the child's own bounding box that lies inside its parent's. */
  ratio: number;
  message: string;
};

function volume(box: THREE.Box3): number {
  const size = box.getSize(new THREE.Vector3());
  return size.x * size.y * size.z;
}

/**
 * The part's own world-space AABB.
 *
 * Deliberately not `Box3.setFromObject`, which walks descendants — a parent's box would
 * then swallow its children and every part would appear perfectly contained.
 */
export function ownWorldBox(mesh: THREE.Mesh): THREE.Box3 {
  mesh.geometry.computeBoundingBox();
  const local = mesh.geometry.boundingBox;
  if (local === null) return new THREE.Box3();
  return local.clone().applyMatrix4(mesh.matrixWorld);
}

/**
 * How much of `child` lies inside `parent`, as a fraction of the child.
 *
 * Flat parts — a pupil disc, an extruded sheet — have zero AABB volume, so the volume
 * ratio is undefined for them. Those fall back to counting corners inside the parent,
 * which degrades sensibly rather than dividing by zero.
 */
export function containmentRatio(child: THREE.Box3, parent: THREE.Box3): number {
  const childVolume = volume(child);
  if (childVolume > 1e-9) {
    const overlap = child.clone().intersect(parent);
    if (overlap.isEmpty()) return 0;
    return Math.min(volume(overlap) / childVolume, 1);
  }

  const { min, max } = child;
  const corners = [
    new THREE.Vector3(min.x, min.y, min.z),
    new THREE.Vector3(min.x, min.y, max.z),
    new THREE.Vector3(min.x, max.y, min.z),
    new THREE.Vector3(min.x, max.y, max.z),
    new THREE.Vector3(max.x, min.y, min.z),
    new THREE.Vector3(max.x, min.y, max.z),
    new THREE.Vector3(max.x, max.y, min.z),
    new THREE.Vector3(max.x, max.y, max.z),
  ];
  return corners.filter((corner) => parent.containsPoint(corner)).length / corners.length;
}

export function containmentWarnings(
  meshes: ReadonlyMap<string, THREE.Mesh>,
  parentOf: ReadonlyMap<string, string>,
): CompileWarning[] {
  const warnings: CompileWarning[] = [];

  for (const [partId, parentId] of parentOf) {
    const child = meshes.get(partId);
    const parent = meshes.get(parentId);
    if (child === undefined || parent === undefined) continue;

    const ratio = containmentRatio(ownWorldBox(child), ownWorldBox(parent));
    if (ratio >= CONTAINMENT_THRESHOLD) continue;

    warnings.push({
      code: "parent_containment",
      partId,
      parentId,
      ratio: Math.round(ratio * 1000) / 1000,
      message:
        `part "${partId}" is only ${(ratio * 100).toFixed(1)}% inside its parent ` +
        `"${parentId}" (threshold ${(CONTAINMENT_THRESHOLD * 100).toFixed(0)}%). ` +
        "parent_id means \"is contained by\" (D-017); if that is not the relationship " +
        "here, the parenting is probably wrong.",
    });
  }

  return warnings.sort((a, b) => (a.partId < b.partId ? -1 : 1));
}
