// Task 1.5 — the golden specs are the point of Phase 1: hand-writing them is what
// proves the schema is expressive enough before any model touches it (spec §7).
//
// These tests are the Phase 1 gate in executable form. If a golden spec stops parsing
// or stops compiling, the schema moved and nobody noticed.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { parseSceneSpec } from "../scenespec";

import { compile } from "./compile";
import { applyClipping, clipPlaneFor } from "./cutaway";
import { applyExplode, planExplode } from "./explode";

const GOLDEN_DIR = resolve(__dirname, "../../../../specs/golden");

const files = readdirSync(GOLDEN_DIR).filter((f) => f.endsWith(".json")).sort();

const EXPECTED_TOPICS = ["animal_cell", "earth_layers", "human_eye"];

describe("golden specs", () => {
  it("ships exactly the three topics Phase 1 requires", () => {
    expect(files.map((f) => basename(f, ".json"))).toEqual(EXPECTED_TOPICS);
  });

  for (const file of files) {
    const topic = basename(file, ".json");

    describe(topic, () => {
      const raw: unknown = JSON.parse(readFileSync(resolve(GOLDEN_DIR, file), "utf8"));

      it("is schema-valid", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error(parsed.errors.join("\n"));
        expect(parsed.ok).toBe(true);
      });

      it("declares the topic its filename claims", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        expect(parsed.spec.topic).toBe(topic);
      });

      it("compiles to a scene graph", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        const result = compile(parsed.spec);
        if (!result.ok) throw new Error(JSON.stringify(result.errors, null, 2));
        expect(result.scene.parts.size).toBe(parsed.spec.parts.length);
        result.scene.dispose();
      });

      it("produces finite geometry for every part", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        const result = compile(parsed.spec);
        if (!result.ok) throw new Error("did not compile");

        for (const [id, { mesh }] of result.scene.parts) {
          const attr = mesh.geometry.getAttribute("position");
          expect(attr, `${id} has no vertices`).toBeDefined();
          expect(attr.count, `${id} is empty`).toBeGreaterThan(0);
          for (let i = 0; i < attr.count * attr.itemSize; i++) {
            if (!Number.isFinite(attr.array[i])) {
              throw new Error(`${id} produced a non-finite vertex at ${i}`);
            }
          }
        }
        result.scene.dispose();
      });

      it("gives every part a human-readable name and at least one alias", () => {
        // Aliases drive part-scoped retrieval in Phase 2 (D5); a golden spec with none
        // would make that phase look better than it is.
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        for (const part of parsed.spec.parts) {
          expect(part.name.trim().length, `${part.id} has no name`).toBeGreaterThan(0);
          expect(part.name, `${part.id} name looks like a placeholder`).not.toMatch(/todo|tbd|xxx/i);
          expect(part.aliases?.length ?? 0, `${part.id} has no aliases`).toBeGreaterThan(0);
        }
      });

      it("uses the reserved golden provenance sentinel (D-003)", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        for (const part of parsed.spec.parts) {
          expect(part.provenance.chunk_ids, `${part.id} provenance`).toEqual(["golden"]);
        }
      });

      it("survives cutaway and a full explode without going non-finite", () => {
        const parsed = parseSceneSpec(raw);
        if (!parsed.ok) throw new Error("not schema-valid");
        const result = compile(parsed.spec);
        if (!result.ok) throw new Error("did not compile");
        const { scene } = result;

        applyClipping(scene, clipPlaneFor(parsed.spec));
        for (const mode of ["top-level", "per-part"] as const) {
          applyExplode(scene, planExplode(scene, mode), 1);
          for (const [id, { mesh }] of scene.parts) {
            const world = mesh.getWorldPosition(new THREE.Vector3());
            expect(world.toArray().every(Number.isFinite), `${id} exploded to NaN`).toBe(true);
          }
        }
        scene.dispose();
      });
    });
  }
});

describe("containment warnings (ruling A(d))", () => {
  // D-017 made parent_id mean "is contained by". These are the warnings the golden
  // specs currently produce; both are the legitimate-exception shape the ruling
  // anticipated, which is why this informs curation rather than blocking.
  const EXPECTED: Record<string, Array<{ partId: string; parentId: string }>> = {
    animal_cell: [{ partId: "nuclear_envelope", parentId: "nucleus" }],
    earth_layers: [],
    human_eye: [{ partId: "fovea", parentId: "retina" }],
  };

  for (const file of files) {
    const topic = basename(file, ".json");
    it(`${topic} produces exactly its known warnings`, () => {
      const parsed = parseSceneSpec(JSON.parse(readFileSync(resolve(GOLDEN_DIR, file), "utf8")));
      if (!parsed.ok) throw new Error(parsed.errors.join("; "));
      const result = compile(parsed.spec);
      if (!result.ok) throw new Error("did not compile");

      expect(
        result.warnings.map((w) => ({ partId: w.partId, parentId: w.parentId })),
      ).toEqual(EXPECTED[topic]);
      for (const warning of result.warnings) {
        expect(warning.code).toBe("parent_containment");
        expect(warning.ratio).toBeGreaterThanOrEqual(0);
        expect(warning.ratio).toBeLessThan(1);
      }
      result.scene.dispose();
    });
  }

  it("a warning never blocks the compile", () => {
    const parsed = parseSceneSpec(
      JSON.parse(readFileSync(resolve(GOLDEN_DIR, "animal_cell.json"), "utf8")),
    );
    if (!parsed.ok) throw new Error("not schema-valid");
    const result = compile(parsed.spec);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.warnings.length).toBeGreaterThan(0);
      result.scene.dispose();
    }
  });
});

describe("the golden sentinel stays inside specs/golden (D-003)", () => {
  it("no spec outside specs/golden uses it", () => {
    // Phase 2 task 2.9 backfills real chunk ids here. Until then this test documents
    // the boundary; after the backfill it becomes the thing that enforces it.
    const outside = resolve(__dirname, "../../../../packages/scenespec/examples");
    const examples = readdirSync(outside).filter((f) => f.endsWith(".json"));
    // The §4 example is the schema's own illustration, not a spec that ships.
    expect(examples).toEqual(["section4_example.json"]);
  });
});
