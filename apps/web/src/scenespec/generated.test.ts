// Mirror of services/api/tests/test_scenespec_schema.py. Both stacks are generated from
// the same JSON Schema (D7), so both must reject the same specs — a constraint enforced
// on only one side is the drift this schema exists to prevent.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { SCHEMA_VERSION, parseSceneSpec } from "./index";

const EXAMPLE = resolve(__dirname, "../../../../packages/scenespec/examples/section4_example.json");

function example(): Record<string, any> {
  return JSON.parse(readFileSync(EXAMPLE, "utf8"));
}

const SCHEMA_FILE = resolve(__dirname, "../../../../packages/scenespec/scenespec.schema.json");

describe("SceneSpec zod schema", () => {
  it("SCHEMA_VERSION matches the schema's own const", () => {
    const schema = JSON.parse(readFileSync(SCHEMA_FILE, "utf8"));
    expect(SCHEMA_VERSION).toBe(schema.properties.schema_version.const);
  });

  it("accepts the example printed in spec §4", () => {
    const result = parseSceneSpec(example());
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.spec.parts).toHaveLength(2);
  });

  it("rejects more than 40 parts", () => {
    const spec = example();
    spec.parts = Array.from({ length: 41 }, (_, i) => ({ ...spec.parts[0], id: `p${i}` }));
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects a part with no provenance (Rule 6)", () => {
    const spec = example();
    delete spec.parts[0].provenance;
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("accepts empty chunk_ids (D-025, schema 1.2)", () => {
    // Reversed deliberately. Requiring a citation forced a model with nothing to cite to
    // cite the nearest plausible chunk, making fabricated provenance mandatory. Zero
    // provenance is legal and derives `provenance_strength: "none"`.
    const spec = example();
    spec.parts[0].provenance.chunk_ids = [];
    const result = parseSceneSpec(spec);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.provenanceStrength[spec.parts[0].id]).toBe("none");
  });

  it("rejects a lathe profile with fewer than 3 points", () => {
    const spec = example();
    spec.parts[1].geometry.profile = [
      [0, -0.4],
      [0.55, 0],
    ];
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects non-hex colors", () => {
    const spec = example();
    spec.parts[0].material.color = "cornflowerblue";
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects geometry outside the closed vocabulary", () => {
    const spec = example();
    spec.parts[0].geometry = { type: "csg_subtract", a: "x", b: "y" };
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects invented fields rather than dropping them", () => {
    const spec = example();
    spec.parts[0].glow_intensity = 3;
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("enforces numeric bounds", () => {
    const spec = example();
    spec.parts[0].geometry.radius = 0;
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("clamps opacity to the unit range", () => {
    const spec = example();
    spec.parts[0].material.opacity = 1.4;
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects a part with no geometry at all", () => {
    const spec = example();
    delete spec.parts[0].geometry;
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("rejects geometry with no discriminating type", () => {
    const spec = example();
    spec.parts[0].geometry = { radius: 1 };
    expect(parseSceneSpec(spec).ok).toBe(false);
  });

  it("applies geometry defaults, matching pydantic (D-018)", () => {
    // Before the discriminator landed, the oneOf compiled to z.any().superRefine(),
    // which validated but threw away the branch's parsed output — so zod applied no
    // geometry defaults while pydantic applied them all. Same schema, two behaviours.
    const spec = example();
    spec.parts[1].geometry = { type: "lathe", profile: [[0, 0], [1, 0], [0, 1]] };
    const result = parseSceneSpec(spec);
    expect(result.ok).toBe(true);
    if (result.ok) {
      const geometry = result.spec.parts[1]!.geometry;
      expect(geometry.type).toBe("lathe");
      if (geometry.type === "lathe") expect(geometry.segments).toBe(32);
    }
  });

  it("accepts the reserved `golden` chunk id (D-003)", () => {
    const spec = example();
    spec.parts[0].provenance.chunk_ids = ["golden"];
    expect(parseSceneSpec(spec).ok).toBe(true);
  });

  it("reports actionable paths, not just a boolean", () => {
    const spec = example();
    spec.parts[0].material.color = "nope";
    const result = parseSceneSpec(spec);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.join(" ")).toContain("parts.0.material.color");
  });
});
