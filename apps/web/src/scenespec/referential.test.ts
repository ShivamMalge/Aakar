// Referential constraints — TypeScript side, driven by the shared fixture set.
//
// The mirror is services/api/tests/test_referential.py, over the same files. The
// cross-stack contract is the (code, path) pair; message text is each stack's own.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { validateReferential } from "@scenespec/referential";
import { describe, expect, it } from "vitest";

import { parseSceneSpec } from "./index";

const DIR = resolve(__dirname, "../../../../packages/scenespec/fixtures/referential");
const files = readdirSync(DIR).filter((f) => f.endsWith(".json")).sort();

type Fixture = {
  case: string;
  note: string;
  expect: Array<{ code: string; path: string }>;
  spec: { parts: Array<{ id: string; parent_id?: string }> };
};

function load(file: string): Fixture {
  return JSON.parse(readFileSync(resolve(DIR, file), "utf8")) as Fixture;
}

describe("referential constraints", () => {
  it("has fixtures on both sides of the accept/reject line", () => {
    const fixtures = files.map(load);
    expect(fixtures.filter((f) => f.expect.length === 0).length).toBeGreaterThanOrEqual(3);
    expect(fixtures.filter((f) => f.expect.length > 0).length).toBeGreaterThanOrEqual(5);
  });

  for (const file of files) {
    const fixture = load(file);
    it(`${basename(file, ".json")} — ${fixture.expect.length} expected`, () => {
      const actual = validateReferential(fixture.spec).map((e) => ({ code: e.code, path: e.path }));
      expect(actual).toEqual(fixture.expect);
    });
  }

  describe("fires at parse, not only at compile", () => {
    for (const file of files) {
      const fixture = load(file);
      it(basename(file, ".json"), () => {
        const result = parseSceneSpec(fixture.spec);
        if (fixture.expect.length === 0) {
          expect(result.ok).toBe(true);
          return;
        }
        // The whole point of the move: a referentially broken spec must fail parse,
        // without anything having to render it first.
        expect(result.ok).toBe(false);
        if (!result.ok) {
          expect(result.issues.map((i) => i.code)).toEqual(fixture.expect.map((e) => e.code));
        }
      });
    }
  });

  it("suggests a near-miss parent id", () => {
    const fixture = load("parent-not-found-near-miss.json");
    const [error] = validateReferential(fixture.spec);
    expect(error?.message).toContain('did you mean "eyeball"?');
  });

  it("does not suggest an unrelated id", () => {
    const [error] = validateReferential({
      parts: [{ id: "eyeball" }, { id: "lens", parent_id: "mitochondrion" }],
    });
    expect(error?.message).not.toContain("did you mean");
  });

  it("accepts all three golden specs", () => {
    const goldenDir = resolve(__dirname, "../../../../specs/golden");
    for (const file of readdirSync(goldenDir).filter((f) => f.endsWith(".json"))) {
      const spec = JSON.parse(readFileSync(resolve(goldenDir, file), "utf8"));
      expect(validateReferential(spec), `${file} has referential errors`).toEqual([]);
    }
  });
});
