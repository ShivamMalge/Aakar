// SceneSpec -> three.js object graph. Deterministic and total (D1): the same spec
// always produces the same graph, and no schema-valid spec makes it throw.
//
// The LLM never writes any of this. It emits the spec; this file is the trusted code
// that builds it (spec Rule 5).
import * as THREE from "three";

import type { Part, SceneSpec } from "../scenespec";

import { type ReferentialError, validateReferential } from "@scenespec/referential";

import { type CompileWarning, containmentWarnings } from "./containment";
import { buildGeometry } from "./geometry";

const DEG_TO_RAD = Math.PI / 180;

export type CompiledPart = {
  readonly part: Part;
  readonly mesh: THREE.Mesh;
  /** The part's own transform.position, before any exploded-view offset. */
  readonly basePosition: THREE.Vector3;
  /** World-space position at rest — the exploded view's radial origin. */
  readonly restWorldPosition: THREE.Vector3;
  /** Bounding-sphere radius at rest; orders concentric parts in the exploded view. */
  readonly restRadius: number;
};

export type CompiledScene = {
  readonly root: THREE.Group;
  readonly parts: ReadonlyMap<string, CompiledPart>;
  /** Draw order for parents-before-children traversal. */
  readonly order: readonly string[];
  readonly centroid: THREE.Vector3;
  /** Radius of the whole assembly; the exploded view's distance unit. */
  readonly radius: number;
  dispose(): void;
};

export type CompileResult =
  | { ok: true; scene: CompiledScene; warnings: CompileWarning[] }
  | { ok: false; errors: ReferentialError[] };

function buildMaterial(part: Part): THREE.MeshStandardMaterial {
  const opacity = part.material.opacity ?? 1;
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(part.material.color),
    roughness: part.material.roughness ?? 0.5,
    metalness: 0,
    opacity,
    transparent: opacity < 1,
    // Concentric translucent shells — an eyeball's sclera/choroid/retina, a cell's
    // membrane over its cytoplasm — are the common case here, and with depth writing
    // on, whichever shell draws first hides every shell inside it. The topic renders
    // as one flat grey ball. Turning it off for translucent parts only is what makes
    // a layered topic legible.
    depthWrite: opacity >= 1,
    // Cross-sections and open-ended cylinders both show backfaces; without this the
    // cutaway (1.3) reveals hollow shells rather than an interior.
    side: THREE.DoubleSide,
  });
}

function applyTransform(mesh: THREE.Mesh, part: Part): THREE.Vector3 {
  const t = part.transform;
  const position = new THREE.Vector3(
    t?.position?.[0] ?? 0,
    t?.position?.[1] ?? 0,
    t?.position?.[2] ?? 0,
  );
  mesh.position.copy(position);
  mesh.rotation.set(
    (t?.rotation?.[0] ?? 0) * DEG_TO_RAD,
    (t?.rotation?.[1] ?? 0) * DEG_TO_RAD,
    (t?.rotation?.[2] ?? 0) * DEG_TO_RAD,
  );
  mesh.scale.set(t?.scale?.[0] ?? 1, t?.scale?.[1] ?? 1, t?.scale?.[2] ?? 1);
  return position;
}

/**
 * Parents before children, so wiring never needs a second pass. Parts whose parent is
 * missing or cyclic are not reachable here — validateGraph rejects those specs first.
 */
function topoOrder(spec: SceneSpec): Part[] {
  const byId = new Map(spec.parts.map((p) => [p.id, p]));
  const out: Part[] = [];
  const placed = new Set<string>();

  const place = (part: Part): void => {
    if (placed.has(part.id)) return;
    const parentId = part.parent_id;
    if (parentId !== undefined) {
      const parent = byId.get(parentId);
      if (parent !== undefined) place(parent);
    }
    placed.add(part.id);
    out.push(part);
  };

  for (const part of spec.parts) place(part);
  return out;
}

export function compile(spec: SceneSpec): CompileResult {
  // `parseSceneSpec` already ran these, so in the normal path this finds nothing. It
  // stays here because `compile` accepts a SceneSpec from anywhere — a hand-built object
  // in a test, a future caller that skipped parse — and must be total either way.
  const errors = validateReferential(spec);
  if (errors.length > 0) return { ok: false, errors };

  const root = new THREE.Group();
  root.name = spec.topic;

  const parts = new Map<string, CompiledPart>();
  const meshes = new Map<string, THREE.Mesh>();
  const order: string[] = [];

  for (const part of topoOrder(spec)) {
    const mesh = new THREE.Mesh(buildGeometry(part.geometry), buildMaterial(part));
    mesh.name = part.id;
    // Raycasting reads this to turn a hit back into a part id (1.2).
    mesh.userData = { partId: part.id, clipExempt: part.clip_exempt ?? false };

    const basePosition = applyTransform(mesh, part);

    const parentId = part.parent_id;
    const parentMesh = parentId !== undefined ? meshes.get(parentId) : undefined;
    (parentMesh ?? root).add(mesh);

    meshes.set(part.id, mesh);
    order.push(part.id);
    parts.set(part.id, {
      part,
      mesh,
      basePosition,
      restWorldPosition: new THREE.Vector3(),
      restRadius: 0,
    });
  }

  root.updateMatrixWorld(true);

  // Rest-state measurements, taken once. The exploded view mutates positions, so these
  // must be captured before anything moves.
  const bounds = new THREE.Box3();
  for (const [id, compiled] of parts) {
    const mesh = compiled.mesh;
    mesh.getWorldPosition(compiled.restWorldPosition);

    mesh.geometry.computeBoundingSphere();
    const sphere = mesh.geometry.boundingSphere;
    const scale = mesh.getWorldScale(new THREE.Vector3());
    const maxScale = Math.max(Math.abs(scale.x), Math.abs(scale.y), Math.abs(scale.z));
    parts.set(id, {
      ...compiled,
      restRadius: Number.isFinite(sphere?.radius) ? (sphere?.radius ?? 0) * maxScale : 0,
    });

    const box = new THREE.Box3().setFromObject(mesh);
    if (!box.isEmpty() && Number.isFinite(box.min.x) && Number.isFinite(box.max.x)) {
      bounds.union(box);
    }
  }

  // Containment is measured after matrices settle and before anything explodes, so the
  // ratio describes the spec's own arrangement rather than a viewer state (ruling A(d)).
  const parentOf = new Map<string, string>();
  for (const [id, compiled] of parts) {
    const parentId = compiled.part.parent_id;
    if (parentId !== undefined && meshes.has(parentId)) parentOf.set(id, parentId);
  }
  const warnings = containmentWarnings(meshes, parentOf);

  const centroid = bounds.isEmpty() ? new THREE.Vector3() : bounds.getCenter(new THREE.Vector3());
  const size = bounds.isEmpty() ? new THREE.Vector3(1, 1, 1) : bounds.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 1e-3);

  return {
    ok: true,
    warnings,
    scene: {
      root,
      parts,
      order,
      centroid,
      radius,
      dispose(): void {
        for (const { mesh } of parts.values()) {
          mesh.geometry.dispose();
          const material = mesh.material;
          if (Array.isArray(material)) material.forEach((m) => m.dispose());
          else material.dispose();
        }
      },
    },
  };
}
