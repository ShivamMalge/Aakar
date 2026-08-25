// One builder per geometry type in the closed vocabulary (spec §4).
//
// Every builder is **total**: it must return a BufferGeometry for any schema-valid
// input, never throw. Schema-valid does not mean sensible — `cylinder` permits
// r_top = r_bottom = 0, and `tube` permits a path whose points are all identical — so
// the degenerate cases are clamped here rather than left to crash three.js downstream.
// `1.7`'s fast-check fuzz is what holds this honest.
import * as THREE from "three";

import type { Part } from "../scenespec";

export type Geometry = Part["geometry"];
export type GeometryType = Geometry["type"];

/**
 * Fixed tessellation. Determinism is the entire point of the compiler (D1), and Phase
 * 3's replay-stability check (3.7) compares rendered screenshots byte-for-byte, so
 * nothing here may depend on viewport, device, time or spec content.
 */
export const TESSELLATION = {
  sphereWidth: 48,
  sphereHeight: 32,
  cylinderRadial: 48,
  coneRadial: 48,
  torusTubular: 72,
  torusRadial: 24,
  capsuleCap: 12,
  capsuleRadial: 32,
  tubeTubular: 96,
  tubeRadial: 16,
} as const;

/** Points closer together than this are the same point. */
const EPSILON = 1e-6;
/** Smallest span we will build a tube along when a path collapses to a single point. */
const MIN_SPAN = 1e-3;

function vec3(p: readonly number[]): THREE.Vector3 {
  return new THREE.Vector3(p[0] ?? 0, p[1] ?? 0, p[2] ?? 0);
}

function vec2(p: readonly number[]): THREE.Vector2 {
  return new THREE.Vector2(p[0] ?? 0, p[1] ?? 0);
}

/**
 * Collapse consecutive duplicate points. CatmullRomCurve3 divides by the distance
 * between successive points, so a repeated point yields NaN vertices — geometry that
 * renders as nothing and poisons any bounding-box computation downstream.
 */
function tubePath(path: readonly (readonly number[])[], closed: boolean): {
  points: THREE.Vector3[];
  closed: boolean;
} {
  const points: THREE.Vector3[] = [];
  for (const raw of path) {
    const v = vec3(raw);
    const last = points[points.length - 1];
    if (last === undefined || last.distanceTo(v) > EPSILON) points.push(v);
  }

  // A closed curve re-joins its own start; an explicit repeat of it is a duplicate.
  const first = points[0];
  const last = points[points.length - 1];
  if (closed && points.length > 2 && first !== undefined && last !== undefined) {
    if (first.distanceTo(last) <= EPSILON) points.pop();
  }

  if (points.length === 0) points.push(new THREE.Vector3());
  if (points.length === 1) {
    // Degenerate but schema-valid: build a minimal visible span rather than crash.
    points.push(points[0]!.clone().add(new THREE.Vector3(MIN_SPAN, 0, 0)));
  }

  // CatmullRomCurve3 needs three points before "closed" means anything.
  return { points, closed: closed && points.length >= 3 };
}

export function buildGeometry(geometry: Geometry): THREE.BufferGeometry {
  switch (geometry.type) {
    case "sphere":
      return new THREE.SphereGeometry(
        geometry.radius,
        TESSELLATION.sphereWidth,
        TESSELLATION.sphereHeight,
      );

    case "box":
      return new THREE.BoxGeometry(geometry.w, geometry.h, geometry.d);

    case "cylinder":
      return new THREE.CylinderGeometry(
        geometry.r_top,
        geometry.r_bottom,
        geometry.height,
        TESSELLATION.cylinderRadial,
        1,
        geometry.open_ended ?? false,
      );

    case "cone":
      return new THREE.ConeGeometry(geometry.radius, geometry.height, TESSELLATION.coneRadial);

    case "torus":
      return new THREE.TorusGeometry(
        geometry.radius,
        geometry.tube,
        TESSELLATION.torusRadial,
        TESSELLATION.torusTubular,
      );

    case "capsule":
      return new THREE.CapsuleGeometry(
        geometry.radius,
        geometry.length,
        TESSELLATION.capsuleCap,
        TESSELLATION.capsuleRadial,
      );

    case "tube": {
      const { points, closed } = tubePath(geometry.path, geometry.closed ?? false);
      const curve = new THREE.CatmullRomCurve3(points, closed);
      return new THREE.TubeGeometry(
        curve,
        TESSELLATION.tubeTubular,
        geometry.radius,
        TESSELLATION.tubeRadial,
        closed,
      );
    }

    case "lathe":
      return new THREE.LatheGeometry(
        geometry.profile.map(vec2),
        geometry.segments ?? 32,
      );

    case "extrude": {
      const shape = new THREE.Shape(geometry.shape.map(vec2));
      return new THREE.ExtrudeGeometry(shape, {
        depth: geometry.depth,
        bevelEnabled: false,
        steps: 1,
      });
    }

    default: {
      // The vocabulary is closed (spec §4). If this stops compiling, the schema grew a
      // geometry type and no builder was written for it — that is the bug, not this line.
      const unreachable: never = geometry;
      throw new Error(`unsupported geometry: ${JSON.stringify(unreachable)}`);
    }
  }
}
