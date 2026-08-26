// Parent-relationship diagnostics (rulings A(d), 11 and 12).
//
// D-017 made `parent_id` mean "is contained by", so a spec that parents parts for
// convenience explodes wrongly with no diagnostic. But the first implementation compared
// axis-aligned bounding boxes and fired on 100% of the legitimate cases in the golden
// specs — a nuclear envelope that surrounds its nucleus, and a fovea that sits on the
// retina's surface. A warning channel that is noisy on day one is ignored by day three,
// and it pre-fills the curation gate with false positives.
//
// Two changes fix that.
//
// 1. CONTAINMENT IS MEASURED AGAINST REAL GEOMETRY, NOT BOXES. Both golden false
//    positives were spheres, where an AABB over-reports badly: the box around a sphere is
//    ~1.9x its volume, and two concentric spheres whose radii differ by 10% have boxes
//    that clip at eight corners. Child vertices are sampled and tested against the
//    parent's actual solid, analytically where the geometry allows it.
//
// 2. THE RELATION IS CLASSIFIED, NOT SCORED. "How much of the child is inside" cannot
//    distinguish an envelope from a mistake. Measuring containment BOTH ways, plus the
//    volume ratio, separates the legal arrangements from the one that is actually wrong.
import * as THREE from "three";

import type { Part, SceneSpec } from "../scenespec";

/** A child at or above this is plainly contained. */
export const CONTAINMENT_THRESHOLD = 0.9;
/** A parent at or above this inside its child means the child is an envelope. */
export const SURROUNDS_THRESHOLD = 0.75;
/** A child this much smaller than its parent can be a surface feature. */
export const SURFACE_VOLUME_RATIO = 0.2;
/**
 * A child whose surface is within this multiple of its own size of its parent is
 * *adjacent* — touching or nearly touching. Branching anatomy (a dendritic tree, an axon
 * arborisation) parents by connectivity, and a part joined end-to-end to its parent has a
 * perfectly clear relation even though it is not inside it. The actual warning is for a
 * child with NO clear relation, which is a different thing from "not contained".
 */
export const ADJACENCY_FACTOR = 1.0;
/** Vertices sampled per mesh. Enough to be stable, cheap enough to run every compile. */
const SAMPLE_LIMIT = 600;

export type ParentRelation =
  | "contained"
  | "surrounds_parent"
  | "surface_attached"
  | "adjacent"
  | "detached";

export type WarningCode = "parent_containment" | "rotated_parent" | "non_uniform_scaled_parent";

export type CompileWarning = {
  code: WarningCode;
  partId: string;
  parentId: string;
  message: string;
  /** Only on `parent_containment`. */
  relation?: ParentRelation;
  ratio?: number;
};

/** What the compiler knows about each part's relationship to its parent. */
export type ContainmentReport = {
  partId: string;
  parentId: string;
  relation: ParentRelation;
  /** Fraction of the child inside the parent. */
  childInParent: number;
  /** Fraction of the parent inside the child — what identifies an envelope. */
  parentInChild: number;
  /** Child volume / parent volume, from bounding boxes. */
  volumeRatio: number;
  /** Surface gap, in multiples of the child's own size. 0 when they touch. */
  relativeGap: number;
};

// --------------------------------------------------------------- inside tests

/**
 * Is `local` inside this geometry, in the geometry's own local space?
 *
 * Returns null when the type has no cheap analytic test (tube, lathe, extrude), so the
 * caller can fall back to the bounding box rather than silently answering wrongly.
 */
function insideGeometry(geometry: Part["geometry"], local: THREE.Vector3): boolean | null {
  switch (geometry.type) {
    case "sphere":
      return local.length() <= geometry.radius;

    case "box":
      return (
        Math.abs(local.x) <= geometry.w / 2 &&
        Math.abs(local.y) <= geometry.h / 2 &&
        Math.abs(local.z) <= geometry.d / 2
      );

    case "cylinder": {
      const half = geometry.height / 2;
      if (Math.abs(local.y) > half) return false;
      // three.js lerps r_bottom at -h/2 to r_top at +h/2.
      const t = (local.y + half) / geometry.height;
      const radius = geometry.r_bottom + (geometry.r_top - geometry.r_bottom) * t;
      return Math.hypot(local.x, local.z) <= radius;
    }

    case "cone": {
      const half = geometry.height / 2;
      if (Math.abs(local.y) > half) return false;
      // Apex at +h/2, full radius at -h/2.
      const radius = geometry.radius * (0.5 - local.y / geometry.height);
      return Math.hypot(local.x, local.z) <= Math.max(radius, 0);
    }

    case "capsule": {
      // A segment of `length` along Y, with hemispherical caps.
      const half = geometry.length / 2;
      const y = Math.max(-half, Math.min(half, local.y));
      return Math.hypot(local.x, local.y - y, local.z) <= geometry.radius;
    }

    case "torus": {
      // three.js builds a torus in the XY plane, hole along Z.
      const ring = Math.hypot(local.x, local.y) - geometry.radius;
      return Math.hypot(ring, local.z) <= geometry.tube;
    }

    default:
      // tube, lathe, extrude — swept and revolved surfaces, no cheap closed form.
      return null;
  }
}

/** Evenly spaced sample of a mesh's own vertices, in world space. */
function sampleWorldVertices(mesh: THREE.Mesh): THREE.Vector3[] {
  const attribute = mesh.geometry.getAttribute("position");
  if (attribute === undefined) return [];

  const total = attribute.count;
  const stride = Math.max(1, Math.ceil(total / SAMPLE_LIMIT));
  const out: THREE.Vector3[] = [];
  for (let i = 0; i < total; i += stride) {
    const vertex = new THREE.Vector3(
      attribute.getX(i),
      attribute.getY(i),
      attribute.getZ(i),
    );
    out.push(vertex.applyMatrix4(mesh.matrixWorld));
  }
  return out;
}

/** The mesh's own world AABB — not `setFromObject`, which would swallow its children. */
export function ownWorldBox(mesh: THREE.Mesh): THREE.Box3 {
  mesh.geometry.computeBoundingBox();
  const local = mesh.geometry.boundingBox;
  if (local === null) return new THREE.Box3();
  return local.clone().applyMatrix4(mesh.matrixWorld);
}

function boxVolume(box: THREE.Box3): number {
  const size = box.getSize(new THREE.Vector3());
  return size.x * size.y * size.z;
}

/**
 * Fraction of `inner`'s sampled vertices that fall inside `outer`.
 *
 * Analytic against the outer solid when its geometry allows; otherwise the outer AABB,
 * which is the old crude behaviour, kept only where there is no better option.
 */
export function fractionInside(
  inner: THREE.Mesh,
  outer: THREE.Mesh,
  outerGeometry: Part["geometry"],
): number {
  const samples = sampleWorldVertices(inner);
  if (samples.length === 0) return 0;

  const toOuterLocal = outer.matrixWorld.clone().invert();
  const outerBox = ownWorldBox(outer);

  let inside = 0;
  for (const world of samples) {
    const local = world.clone().applyMatrix4(toOuterLocal);
    const analytic = insideGeometry(outerGeometry, local);
    if (analytic === null ? outerBox.containsPoint(world) : analytic) inside += 1;
  }
  return inside / samples.length;
}

// ------------------------------------------------------------- classification

export function classify(
  childInParent: number,
  parentInChild: number,
  volumeRatio: number,
  /** Surface gap between child and parent, in multiples of the child's own size. */
  relativeGap: number,
): ParentRelation {
  // Plainly inside its parent. The normal case, and silent.
  if (childInParent >= CONTAINMENT_THRESHOLD) return "contained";

  // The child encloses the parent instead — a nuclear envelope around its nucleus.
  // Legal, and structurally the opposite of a mistake.
  if (parentInChild >= SURROUNDS_THRESHOLD && volumeRatio > 1) return "surrounds_parent";

  // A small feature sitting on the parent's surface — a fovea on the retina. Its
  // centre is inside the parent while part of its body protrudes.
  if (volumeRatio < SURFACE_VOLUME_RATIO && childInParent > 0) return "surface_attached";

  // Touching or nearly touching — joined rather than contained. Legal and common in
  // branching structures, and not what the warning is for.
  if (relativeGap <= ADJACENCY_FACTOR) return "adjacent";

  // Not inside it, not around it, not on it, not even near it. This is the warning.
  return "detached";
}

/** Surface gap between two boxes as a multiple of `child`'s own diagonal. 0 if they meet. */
export function relativeGap(child: THREE.Box3, parent: THREE.Box3): number {
  const size = child.getSize(new THREE.Vector3());
  const diagonal = size.length();
  if (diagonal < 1e-9) return Infinity;

  // Per-axis separation; zero on every axis means the boxes intersect.
  const dx = Math.max(0, parent.min.x - child.max.x, child.min.x - parent.max.x);
  const dy = Math.max(0, parent.min.y - child.max.y, child.min.y - parent.max.y);
  const dz = Math.max(0, parent.min.z - child.max.z, child.min.z - parent.max.z);
  return Math.hypot(dx, dy, dz) / diagonal;
}

export function analyseContainment(
  spec: SceneSpec,
  meshes: ReadonlyMap<string, THREE.Mesh>,
): ContainmentReport[] {
  const partById = new Map(spec.parts.map((part) => [part.id, part]));
  const reports: ContainmentReport[] = [];

  for (const part of spec.parts) {
    const parentId = part.parent_id;
    if (parentId === undefined) continue;

    const child = meshes.get(part.id);
    const parent = meshes.get(parentId);
    const parentPart = partById.get(parentId);
    if (child === undefined || parent === undefined || parentPart === undefined) continue;

    const childInParent = fractionInside(child, parent, parentPart.geometry);
    const parentInChild = fractionInside(parent, child, part.geometry);

    const childBox = ownWorldBox(child);
    const parentBox = ownWorldBox(parent);
    const parentVolume = boxVolume(parentBox);
    const volumeRatio = parentVolume > 1e-9 ? boxVolume(childBox) / parentVolume : Infinity;
    const gap = relativeGap(childBox, parentBox);

    reports.push({
      partId: part.id,
      parentId,
      relation: classify(childInParent, parentInChild, volumeRatio, gap),
      childInParent: Math.round(childInParent * 1000) / 1000,
      parentInChild: Math.round(parentInChild * 1000) / 1000,
      volumeRatio: Math.round(volumeRatio * 1000) / 1000,
      relativeGap: Math.round(gap * 1000) / 1000,
    });
  }

  return reports.sort((a, b) => (a.partId < b.partId ? -1 : 1));
}

// ----------------------------------------------------------------- warnings

const IDENTITY_ROTATION = (rotation: readonly number[] | undefined): boolean =>
  rotation === undefined || rotation.every((value) => value === 0);

const UNIFORM_SCALE = (scale: readonly number[] | undefined): boolean =>
  scale === undefined || (scale[0] === scale[1] && scale[1] === scale[2]);

/**
 * Warnings about a part's relationship to its parent.
 *
 * Only `detached` containment warns. `contained` is normal; `surrounds_parent` and
 * `surface_attached` are legal arrangements reported through `ContainmentReport` for
 * anyone who wants them, but they do not consume the warning channel.
 *
 * Transform warnings (ruling 11) are surfaced, never forbidden: rotating a parent to
 * carry its subtree is correct scene-graph behaviour and a legitimate authoring tool. It
 * is worth flagging because it is also the shape of a common authoring error — a -90 deg
 * rotation on an axon hillock turned an entire axon at right angles to where it was
 * authored. Non-uniform scale on a parent additionally skews every descendant, which is
 * almost never what an author means.
 */
export function containmentWarnings(
  spec: SceneSpec,
  meshes: ReadonlyMap<string, THREE.Mesh>,
): CompileWarning[] {
  const warnings: CompileWarning[] = [];

  for (const report of analyseContainment(spec, meshes)) {
    if (report.relation !== "detached") continue;
    warnings.push({
      code: "parent_containment",
      partId: report.partId,
      parentId: report.parentId,
      relation: report.relation,
      ratio: report.childInParent,
      message:
        `part "${report.partId}" is only ${(report.childInParent * 100).toFixed(1)}% inside ` +
        `its parent "${report.parentId}" — it does not surround it, sit on its surface, ` +
        `or touch it (gap ${report.relativeGap.toFixed(2)}x its own size). parent_id ` +
        'means "is contained by" (D-017); if that is not the relationship here, the ' +
        "parenting is probably wrong.",
    });
  }

  const hasChildren = new Set(
    spec.parts.map((part) => part.parent_id).filter((id): id is string => id !== undefined),
  );

  for (const part of spec.parts) {
    if (!hasChildren.has(part.id)) continue;
    const transform = part.transform;
    if (transform === undefined) continue;

    if (!IDENTITY_ROTATION(transform.rotation)) {
      warnings.push({
        code: "rotated_parent",
        partId: part.id,
        parentId: part.parent_id ?? "",
        message:
          `part "${part.id}" has a non-identity rotation and has children, so it turns ` +
          "its whole subtree. That is legitimate — but if the children were positioned " +
          "in world coordinates, they will not land where they were authored.",
      });
    }

    if (!UNIFORM_SCALE(transform.scale)) {
      warnings.push({
        code: "non_uniform_scaled_parent",
        partId: part.id,
        parentId: part.parent_id ?? "",
        message:
          `part "${part.id}" has a non-uniform scale and has children, so every ` +
          "descendant is skewed by it. Legal, and rarely intended.",
      });
    }
  }

  return warnings;
}
