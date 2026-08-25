// Cutaway (task 1.3). The clipping plane comes from the spec; parts may opt out with
// `clip_exempt` (spec §4) — a label anchor or an outer marker that should survive the
// cut.
import * as THREE from "three";

import type { SceneSpec } from "../scenespec";

import type { CompiledScene } from "./compile";

/** The spec's plane, or null when the topic declares no cutaway. */
export function clipPlaneFor(spec: SceneSpec): THREE.Plane | null {
  const cutaway = spec.cutaway;
  if (cutaway === undefined || !cutaway.enabled) return null;

  const plane = cutaway.plane;
  // `enabled: true` with no plane is schema-legal; default to slicing through the
  // origin on Z, which is the cross-section a reader expects from a front view.
  const normal = new THREE.Vector3(
    plane?.normal?.[0] ?? 0,
    plane?.normal?.[1] ?? 0,
    plane?.normal?.[2] ?? 1,
  );
  if (normal.lengthSq() <= 1e-12) normal.set(0, 0, 1);

  return new THREE.Plane(normal.normalize(), plane?.constant ?? 0);
}

/**
 * Apply or clear clipping across the scene. Renderer-level `localClippingEnabled` must
 * be on for this to have any effect.
 */
export function applyClipping(scene: CompiledScene, plane: THREE.Plane | null): void {
  for (const { mesh, part } of scene.parts.values()) {
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      const exempt = part.clip_exempt ?? false;
      material.clippingPlanes = plane !== null && !exempt ? [plane] : [];
      material.clipShadows = true;
      material.needsUpdate = true;
    }
  }
}
