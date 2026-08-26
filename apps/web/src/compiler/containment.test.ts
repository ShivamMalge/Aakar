// Parent-relationship diagnostics (rulings A(d), 11, 12).
//
// The first implementation fired on 100% of the legitimate cases in the golden specs. The
// target here is zero warnings on correct structures AND a warning that still fires on an
// incorrect one — a quiet channel and a useless channel look identical from the outside,
// so both directions are asserted.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { parseSceneSpec, type SceneSpec } from "../scenespec";

import { compile } from "./compile";
import { analyseContainment, classify, type ParentRelation } from "./containment";

const SPEC_DIRS = [
  resolve(__dirname, "../../../../specs/golden"),
  resolve(__dirname, "../../../../specs/stress"),
];

function allSpecs(): Array<{ topic: string; spec: SceneSpec }> {
  const out: Array<{ topic: string; spec: SceneSpec }> = [];
  for (const dir of SPEC_DIRS) {
    for (const file of readdirSync(dir).filter((f) => f.endsWith(".json")).sort()) {
      const parsed = parseSceneSpec(JSON.parse(readFileSync(resolve(dir, file), "utf8")));
      if (!parsed.ok) throw new Error(`${file}: ${parsed.errors.join("; ")}`);
      out.push({ topic: basename(file, ".json"), spec: parsed.spec });
    }
  }
  return out;
}

function meshesOf(spec: SceneSpec) {
  const result = compile(spec);
  if (!result.ok) throw new Error(JSON.stringify(result.errors));
  return result;
}

describe("relation classification", () => {
  // classify(childInParent, parentInChild, volumeRatio, relativeGap)
  it("a child inside its parent is contained", () => {
    expect(classify(1, 0, 0.1, 0)).toBe("contained");
  });

  it("a child that encloses its parent surrounds it, not a mistake", () => {
    // The nuclear envelope: the nucleus is entirely inside it, and it is larger.
    expect(classify(0, 1, 1.3, 0)).toBe("surrounds_parent");
  });

  it("a small feature on a big parent is surface-attached", () => {
    // The fovea on the retina.
    expect(classify(0.876, 0, 0.001, 0)).toBe("surface_attached");
  });

  it("a touching sibling-sized part is adjacent, not detached", () => {
    // A dendritic branch joined end-to-end to its trunk.
    expect(classify(0.05, 0.004, 0.5, 0)).toBe("adjacent");
  });

  it("a part far from its parent is detached — the actual warning", () => {
    expect(classify(0, 0, 0.5, 4)).toBe("detached");
  });

  it("the gap is what separates adjacent from detached", () => {
    const args = [0.0, 0.0, 0.5] as const;
    expect(classify(...args, 0.9)).toBe("adjacent");
    expect(classify(...args, 1.1)).toBe("detached");
  });
});

describe("every shipped spec", () => {
  for (const { topic, spec } of allSpecs()) {
    it(`${topic} produces no warnings`, () => {
      const result = meshesOf(spec);
      expect(
        result.warnings.map((w) => `${w.code}:${w.partId}`),
        `${topic} should be silent`,
      ).toEqual([]);
      result.scene.dispose();
    });

    it(`${topic} classifies every parented part`, () => {
      const result = meshesOf(spec);
      const meshes = new Map([...result.scene.parts].map(([id, p]) => [id, p.mesh]));
      const reports = analyseContainment(spec, meshes);
      const parented = spec.parts.filter((p) => p.parent_id !== undefined).length;

      expect(reports).toHaveLength(parented);
      const legal: ParentRelation[] = [
        "contained",
        "surrounds_parent",
        "surface_attached",
        "adjacent",
      ];
      for (const report of reports) {
        expect(legal, `${report.partId} -> ${report.parentId}`).toContain(report.relation);
      }
      result.scene.dispose();
    });
  }
});

describe("the relation travels with the part (D-031)", () => {
  for (const { topic, spec } of allSpecs()) {
    it(`${topic} attaches a relation to every parented part`, () => {
      const result = meshesOf(spec);
      for (const part of spec.parts) {
        const compiled = result.scene.parts.get(part.id);
        if (part.parent_id === undefined) {
          expect(compiled?.containment, `${part.id} is top-level`).toBeUndefined();
        } else {
          // The curation gate reads this rather than reimplementing the geometry tests.
          expect(compiled?.containment?.parentId, `${part.id}`).toBe(part.parent_id);
          expect(compiled?.containment?.relation).toBeDefined();
        }
      }
      result.scene.dispose();
    });
  }
});

describe("the warning still fires", () => {
  /** A part parented to something it is nowhere near. */
  function detachedSpec(): SceneSpec {
    const parsed = parseSceneSpec({
      schema_version: "1.2",
      topic: "detached_case",
      title: "Detached",
      parts: [
        {
          id: "trunk",
          name: "Trunk",
          geometry: { type: "sphere", radius: 0.5 },
          material: { color: "#aabbcc" },
          provenance: { chunk_ids: ["golden"] },
        },
        {
          id: "floater",
          name: "Floater",
          parent_id: "trunk",
          // Ten units away from a half-unit parent: no containment, no contact.
          transform: { position: [10, 0, 0] },
          geometry: { type: "sphere", radius: 0.4 },
          material: { color: "#ccbbaa" },
          provenance: { chunk_ids: ["golden"] },
        },
      ],
    });
    if (!parsed.ok) throw new Error(parsed.errors.join("; "));
    return parsed.spec;
  }

  it("warns about a genuinely detached child", () => {
    const result = meshesOf(detachedSpec());
    const containment = result.warnings.filter((w) => w.code === "parent_containment");
    expect(containment).toHaveLength(1);
    expect(containment[0]?.partId).toBe("floater");
    expect(containment[0]?.relation).toBe("detached");
    result.scene.dispose();
  });

  it("names the gap in the message, so the warning is actionable", () => {
    const result = meshesOf(detachedSpec());
    expect(result.warnings[0]?.message).toMatch(/gap [\d.]+x its own size/);
    result.scene.dispose();
  });
});

describe("transform warnings are surfaced, not forbidden (ruling 11)", () => {
  function spec(transform: Record<string, unknown>): SceneSpec {
    const parsed = parseSceneSpec({
      schema_version: "1.2",
      topic: "transform_case",
      title: "Transform",
      parts: [
        {
          id: "parent_part",
          name: "Parent",
          transform,
          geometry: { type: "sphere", radius: 1 },
          material: { color: "#aabbcc" },
          provenance: { chunk_ids: ["golden"] },
        },
        {
          id: "child_part",
          name: "Child",
          parent_id: "parent_part",
          geometry: { type: "sphere", radius: 0.2 },
          material: { color: "#ccbbaa" },
          provenance: { chunk_ids: ["golden"] },
        },
      ],
    });
    if (!parsed.ok) throw new Error(parsed.errors.join("; "));
    return parsed.spec;
  }

  it("warns when a rotated part has children", () => {
    const result = meshesOf(spec({ rotation: [0, 0, -90] }));
    expect(result.warnings.map((w) => w.code)).toContain("rotated_parent");
    result.scene.dispose();
  });

  it("warns when a non-uniformly scaled part has children", () => {
    const result = meshesOf(spec({ scale: [1, 2, 1] }));
    expect(result.warnings.map((w) => w.code)).toContain("non_uniform_scaled_parent");
    result.scene.dispose();
  });

  it("does not warn about uniform scale — that carries a subtree cleanly", () => {
    const result = meshesOf(spec({ scale: [2, 2, 2] }));
    expect(result.warnings.map((w) => w.code)).not.toContain("non_uniform_scaled_parent");
    result.scene.dispose();
  });

  it("compiles anyway — a rotated parent is legal, not an error", () => {
    // Ruling 11: rotating a parent to carry its subtree is correct scene-graph
    // behaviour and a legitimate authoring tool. It is flagged, never blocked.
    const result = compile(spec({ rotation: [0, 0, -90] }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.warnings.length).toBeGreaterThan(0);
      result.scene.dispose();
    }
  });
});
