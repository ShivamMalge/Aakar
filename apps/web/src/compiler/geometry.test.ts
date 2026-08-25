// One test per builder in the closed vocabulary (spec §4), plus the degenerate cases
// the schema permits but three.js does not survive on its own.
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { buildGeometry, type Geometry } from "./geometry";

function vertexCount(g: THREE.BufferGeometry): number {
  return g.getAttribute("position")?.count ?? 0;
}

function allFinite(g: THREE.BufferGeometry): boolean {
  const attr = g.getAttribute("position");
  if (attr === undefined) return false;
  for (let i = 0; i < attr.count * attr.itemSize; i++) {
    if (!Number.isFinite(attr.array[i])) return false;
  }
  return true;
}

/** Every builder must produce real, finite, non-empty geometry. */
function expectSane(g: THREE.BufferGeometry): void {
  expect(vertexCount(g)).toBeGreaterThan(0);
  expect(allFinite(g)).toBe(true);
}

const CASES: ReadonlyArray<[string, Geometry, new () => THREE.BufferGeometry]> = [
  ["sphere", { type: "sphere", radius: 1 }, THREE.SphereGeometry],
  ["box", { type: "box", w: 1, h: 2, d: 3 }, THREE.BoxGeometry],
  [
    "cylinder",
    { type: "cylinder", r_top: 1, r_bottom: 2, height: 3, open_ended: false },
    THREE.CylinderGeometry,
  ],
  ["cone", { type: "cone", radius: 1, height: 2 }, THREE.ConeGeometry],
  ["torus", { type: "torus", radius: 2, tube: 0.5 }, THREE.TorusGeometry],
  ["capsule", { type: "capsule", radius: 0.5, length: 2 }, THREE.CapsuleGeometry],
  [
    "tube",
    { type: "tube", path: [[0, 0, 0], [1, 1, 0], [2, 0, 0]], radius: 0.2, closed: false },
    THREE.TubeGeometry,
  ],
  [
    "lathe",
    { type: "lathe", profile: [[0, -0.4], [0.55, 0], [0, 0.4]], segments: 48 },
    THREE.LatheGeometry,
  ],
  [
    "extrude",
    { type: "extrude", shape: [[0, 0], [1, 0], [1, 1], [0, 1]], depth: 0.5 },
    THREE.ExtrudeGeometry,
  ],
];

describe("geometry builders", () => {
  for (const [name, geometry, ctor] of CASES) {
    it(`builds ${name}`, () => {
      const g = buildGeometry(geometry);
      expect(g).toBeInstanceOf(ctor);
      expectSane(g);
    });
  }

  it("covers all nine vocabulary types", () => {
    expect(new Set(CASES.map(([n]) => n)).size).toBe(9);
  });

  it("is deterministic — the same spec builds identical vertices (D1)", () => {
    const geometry: Geometry = { type: "sphere", radius: 1.5 };
    const a = buildGeometry(geometry).getAttribute("position").array;
    const b = buildGeometry(geometry).getAttribute("position").array;
    expect(Array.from(a)).toEqual(Array.from(b));
  });

  it("honours the lathe segment count", () => {
    const few = buildGeometry({ type: "lathe", profile: [[0, 0], [1, 0], [0, 1]], segments: 3 });
    const many = buildGeometry({ type: "lathe", profile: [[0, 0], [1, 0], [0, 1]], segments: 64 });
    expect(vertexCount(many)).toBeGreaterThan(vertexCount(few));
  });

  it("honours open_ended on a cylinder", () => {
    const capped = buildGeometry({
      type: "cylinder", r_top: 1, r_bottom: 1, height: 2, open_ended: false,
    });
    const open = buildGeometry({
      type: "cylinder", r_top: 1, r_bottom: 1, height: 2, open_ended: true,
    });
    expect(vertexCount(open)).toBeLessThan(vertexCount(capped));
  });

  describe("degenerate but schema-valid input stays total", () => {
    it("a tube whose path is one repeated point", () => {
      expectSane(
        buildGeometry({
          type: "tube",
          path: [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
          radius: 0.1,
          closed: false,
        }),
      );
    });

    it("a closed tube with too few distinct points to close", () => {
      expectSane(
        buildGeometry({
          type: "tube", path: [[0, 0, 0], [1, 0, 0]], radius: 0.1, closed: true,
        }),
      );
    });

    it("a closed tube that repeats its first point last", () => {
      expectSane(
        buildGeometry({
          type: "tube",
          path: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 0, 0]],
          radius: 0.1,
          closed: true,
        }),
      );
    });

    it("a cylinder with both radii zero", () => {
      // The schema allows r_top and r_bottom to be 0 independently (minimum: 0).
      const g = buildGeometry({
        type: "cylinder", r_top: 0, r_bottom: 0, height: 1, open_ended: false,
      });
      expect(allFinite(g)).toBe(true);
    });

    it("a lathe profile with no radial extent", () => {
      const g = buildGeometry({
        type: "lathe", profile: [[0, 0], [0, 1], [0, 2]], segments: 8,
      });
      expect(allFinite(g)).toBe(true);
    });

    it("an extrude over a collinear shape", () => {
      const g = buildGeometry({
        type: "extrude", shape: [[0, 0], [1, 0], [2, 0]], depth: 1,
      });
      expect(allFinite(g)).toBe(true);
    });
  });
});
