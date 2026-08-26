// Derived provenance strength (D-025, schema 1.2) — zod side.
//
// The mirror of services/api/tests/test_provenance.py, over the same fixtures.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import {
  provenanceStrengths,
  strengthCounts,
  ungroundedParts,
} from "@scenespec/provenance";
import { describe, expect, it } from "vitest";

import { parseSceneSpec } from "./index";

const DIR = resolve(__dirname, "../../../../packages/scenespec/fixtures/provenance");
const files = readdirSync(DIR).filter((f) => f.endsWith(".json")).sort();

type Fixture = { case: string; note: string; expect: Record<string, string>; spec: never };

function load(file: string): Fixture {
  return JSON.parse(readFileSync(resolve(DIR, file), "utf8")) as Fixture;
}

describe("provenance strength", () => {
  it("the corpus covers all three states", () => {
    const seen = new Set(files.flatMap((f) => Object.values(load(f).expect)));
    expect([...seen].sort()).toEqual(["none", "strong", "weak"]);
  });

  for (const file of files) {
    const fixture = load(file);
    it(`${basename(file, ".json")} — ${JSON.stringify(fixture.expect)}`, () => {
      expect(provenanceStrengths(fixture.spec), fixture.note).toEqual(fixture.expect);
    });

    it(`${basename(file, ".json")} still parses`, () => {
      // Zero provenance is legal, not an error — the whole point of D-025.
      const result = parseSceneSpec(fixture.spec);
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.provenanceStrength).toEqual(fixture.expect);
    });
  }

  it("accepts an empty chunk_ids array", () => {
    const result = parseSceneSpec({
      schema_version: "1.2",
      topic: "zero_provenance",
      title: "Zero provenance",
      parts: [
        {
          id: "invented",
          name: "Invented",
          geometry: { type: "sphere", radius: 1 },
          material: { color: "#aabbcc" },
          provenance: { chunk_ids: [] },
        },
      ],
    });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.provenanceStrength["invented"]).toBe("none");
  });

  it("rejects an author-supplied strength — it is derived", () => {
    const fixture = load("strong-cited-and-quoted.json");
    const tampered = JSON.parse(JSON.stringify(fixture.spec));
    tampered.parts[0].provenance_strength = "strong";
    expect(parseSceneSpec(tampered).ok).toBe(false);
  });

  it("counts and lists the ungrounded parts for the curation gate", () => {
    const fixture = load("mixed-all-three-states.json");
    expect(strengthCounts(fixture.spec)).toEqual({ strong: 1, weak: 1, none: 1 });
    expect(ungroundedParts(fixture.spec)).toEqual(["invented"]);
  });
});
