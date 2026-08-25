// Task 1.7 — the compiler must be **total** over schema-valid specs: it may reject a
// spec, but it may never crash on one, and it may never emit NaN geometry (which
// renders as nothing and silently poisons every bounding-box computation downstream).
//
// D-001: fast-check rather than hypothesis. The compiler is TypeScript, so in-process
// generation is what buys shrinking on failure — the entire value of property testing.
import fc from "fast-check";
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { parseSceneSpec, type SceneSpec } from "../scenespec";

import { compile } from "./compile";
import { applyClipping, clipPlaneFor } from "./cutaway";
import { applyExplode, planExplode } from "./explode";

// ---------------------------------------------------------------------------
// Arbitraries. These mirror scenespec.schema.json bounds; the first property
// asserts that mirroring is faithful, so schema drift fails here rather than
// quietly narrowing what gets fuzzed.
// ---------------------------------------------------------------------------

const ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_".split("");
const HEX = "0123456789abcdefABCDEF".split("");

const coord = fc.double({ min: -1000, max: 1000, noNaN: true });
const positive = fc.double({ min: 0.001, max: 100, noNaN: true });
const nonNegative = fc.double({ min: 0, max: 100, noNaN: true });
const unit = fc.double({ min: 0, max: 1, noNaN: true });
const angle = fc.double({ min: -360, max: 360, noNaN: true });

const vec3 = fc.tuple(coord, coord, coord);
const vec2 = fc.tuple(coord, coord);

const hexColor = fc
  .array(fc.constantFrom(...HEX), { minLength: 6, maxLength: 6 })
  .map((a) => `#${a.join("")}`);

const shortId = fc
  .array(fc.constantFrom(...ID_CHARS), { minLength: 1, maxLength: 12 })
  .map((a) => a.join(""));

const geometry = fc.oneof(
  fc.record({ type: fc.constant("sphere" as const), radius: positive }),
  fc.record({ type: fc.constant("box" as const), w: positive, h: positive, d: positive }),
  fc.record({
    type: fc.constant("cylinder" as const),
    r_top: nonNegative,
    r_bottom: nonNegative,
    height: positive,
    open_ended: fc.boolean(),
  }),
  fc.record({ type: fc.constant("cone" as const), radius: positive, height: positive }),
  fc.record({ type: fc.constant("torus" as const), radius: positive, tube: positive }),
  fc.record({ type: fc.constant("capsule" as const), radius: positive, length: positive }),
  fc.record({
    type: fc.constant("tube" as const),
    path: fc.array(vec3, { minLength: 2, maxLength: 12 }),
    radius: positive,
    closed: fc.boolean(),
  }),
  fc.record({
    type: fc.constant("lathe" as const),
    profile: fc.array(vec2, { minLength: 3, maxLength: 12 }),
    segments: fc.integer({ min: 3, max: 64 }),
  }),
  fc.record({
    type: fc.constant("extrude" as const),
    shape: fc.array(vec2, { minLength: 3, maxLength: 12 }),
    depth: positive,
  }),
);

const material = fc.record({ color: hexColor, opacity: unit, roughness: unit });

const transform = fc.record({
  position: vec3,
  rotation: fc.tuple(angle, angle, angle),
  scale: fc.tuple(positive, positive, positive),
});

const provenance = fc.record({
  chunk_ids: fc.array(fc.string({ minLength: 1, maxLength: 16 }), {
    minLength: 1,
    maxLength: 4,
  }),
});

function partAt(index: number, parentIds: readonly string[]) {
  return fc.record({
    id: fc.constant(`p${index}`),
    name: fc.string({ minLength: 1, maxLength: 40 }),
    geometry,
    material,
    transform,
    provenance,
    clip_exempt: fc.boolean(),
    importance: fc.constantFrom("core" as const, "secondary" as const),
    // Only ancestors already emitted, so the graph is a tree by construction.
    parent_id:
      parentIds.length === 0
        ? fc.constant(undefined)
        : fc.option(fc.constantFrom(...parentIds), { nil: undefined }),
  });
}

/** Schema-valid AND graph-valid: parents always resolve, never cycle. */
const treeSpec = fc.integer({ min: 1, max: 6 }).chain((count) =>
  fc
    .tuple(
      ...Array.from({ length: count }, (_, i) =>
        partAt(i, Array.from({ length: i }, (_, j) => `p${j}`)),
      ),
    )
    .chain((parts) =>
      fc.record({
        schema_version: fc.constant("1.0" as const),
        topic: fc.constant("fuzz_topic"),
        title: fc.string({ minLength: 1, maxLength: 60 }),
        parts: fc.constant(parts),
        cutaway: fc.option(
          fc.record({
            enabled: fc.boolean(),
            plane: fc.record({ normal: vec3, constant: coord }),
          }),
          { nil: undefined },
        ),
      }),
    ),
);

/** Schema-valid but the graph may be nonsense: dangling parents, duplicates, cycles. */
const chaoticSpec = fc
  .array(
    fc.record({
      id: shortId,
      name: fc.string({ minLength: 1, maxLength: 40 }),
      geometry,
      material,
      transform,
      provenance,
      clip_exempt: fc.boolean(),
      importance: fc.constantFrom("core" as const, "secondary" as const),
      parent_id: fc.option(shortId, { nil: undefined }),
    }),
    { minLength: 1, maxLength: 6 },
  )
  .map((parts) => ({
    schema_version: "1.0" as const,
    topic: "fuzz_topic",
    title: "Fuzz",
    parts,
  }));

// ---------------------------------------------------------------------------

function everyVertexFinite(root: THREE.Object3D): boolean {
  let finite = true;
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const attr = (object.geometry as THREE.BufferGeometry).getAttribute("position");
    if (attr === undefined) return;
    for (let i = 0; i < attr.count * attr.itemSize; i++) {
      if (!Number.isFinite(attr.array[i])) finite = false;
    }
  });
  return finite;
}

describe("compiler totality (property-tested, D-001)", () => {
  it("every generated tree spec really is schema-valid", () => {
    // Guards the rest of this file: if the arbitraries drift from the schema, the
    // fuzz below would be exercising specs the real system would have rejected.
    fc.assert(
      fc.property(treeSpec, (candidate) => {
        const parsed = parseSceneSpec(candidate);
        if (!parsed.ok) throw new Error(parsed.errors.join("; "));
      }),
      { numRuns: 100 },
    );
  });

  it("compiles every schema-valid tree spec without throwing", () => {
    fc.assert(
      fc.property(treeSpec, (candidate) => {
        const result = compile(candidate as unknown as SceneSpec);
        if (!result.ok) throw new Error(`tree spec rejected: ${JSON.stringify(result.errors)}`);
        result.scene.dispose();
      }),
      { numRuns: 100 },
    );
  });

  it("never produces NaN geometry", () => {
    fc.assert(
      fc.property(treeSpec, (candidate) => {
        const result = compile(candidate as unknown as SceneSpec);
        if (!result.ok) return;
        expect(everyVertexFinite(result.scene.root)).toBe(true);
        expect(Number.isFinite(result.scene.radius)).toBe(true);
        expect(result.scene.centroid.toArray().every(Number.isFinite)).toBe(true);
        result.scene.dispose();
      }),
      { numRuns: 100 },
    );
  });

  it("survives an arbitrary graph — rejects it, but never crashes", () => {
    fc.assert(
      fc.property(chaoticSpec, (candidate) => {
        // The contract is total: a result, never an exception.
        const result = compile(candidate as unknown as SceneSpec);
        if (result.ok) result.scene.dispose();
        else expect(result.errors.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 },
    );
  });

  it("explodes and clips any compiled scene without producing NaN", () => {
    fc.assert(
      fc.property(
        treeSpec,
        fc.constantFrom("top-level" as const, "per-part" as const),
        fc.double({ min: 0, max: 1, noNaN: true }),
        (candidate, mode, factor) => {
          const result = compile(candidate as unknown as SceneSpec);
          if (!result.ok) return;
          const { scene } = result;

          applyExplode(scene, planExplode(scene, mode), factor);
          applyClipping(scene, clipPlaneFor(candidate as unknown as SceneSpec));

          for (const { mesh } of scene.parts.values()) {
            expect(mesh.position.toArray().every(Number.isFinite)).toBe(true);
          }
          expect(everyVertexFinite(scene.root)).toBe(true);
          scene.dispose();
        },
      ),
      { numRuns: 100 },
    );
  });

  it("explode at factor 0 is exactly the identity, for any mode", () => {
    fc.assert(
      fc.property(
        treeSpec,
        fc.constantFrom("top-level" as const, "per-part" as const),
        (candidate, mode) => {
          const result = compile(candidate as unknown as SceneSpec);
          if (!result.ok) return;
          const { scene } = result;

          // -0 and +0 are the same point, but IEEE 754 makes (-0 + 0) === +0 and
          // toEqual compares zeros by sign. Normalise before comparing, or this
          // property fails on a difference nothing can observe.
          const positions = () =>
            [...scene.parts.values()].map((p) =>
              p.mesh.position.toArray().map((v) => (v === 0 ? 0 : v)),
            );

          const before = positions();
          const plan = planExplode(scene, mode);
          applyExplode(scene, plan, 1);
          applyExplode(scene, plan, 0);

          expect(positions()).toEqual(before);
          scene.dispose();
        },
      ),
      { numRuns: 50 },
    );
  });
});
