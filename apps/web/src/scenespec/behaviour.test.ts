// Behavioural conformance — zod side.
//
// The mirror of services/api/tests/test_behavioural_conformance.py, over the same
// fixtures. Verdict agreement is not behavioural agreement: before D-018 zod applied no
// geometry defaults while pydantic applied them all, and the verdict corpus could not
// see it because both stacks said "valid".
//
// The expected form is derived from the schema, not from either parser — generating it
// from one stack would make that stack's bug the expected answer.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { canonical } from "@scenespec/canonical";
import { describe, expect, it } from "vitest";

import { parseSceneSpec } from "./index";

const PACKAGE = resolve(__dirname, "../../../../packages/scenespec");
const INPUT_DIR = resolve(PACKAGE, "fixtures/behaviour/input");
const EXPECTED_DIR = resolve(PACKAGE, "fixtures/behaviour/expected");

const inputs = readdirSync(INPUT_DIR)
  .filter((f) => f.endsWith(".json"))
  .sort();

function read(dir: string, file: string): unknown {
  return JSON.parse(readFileSync(resolve(dir, file), "utf8"));
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Name the field and both values — "not equal" is not a usable failure here. */
function differences(expected: unknown, actual: unknown, where = ""): string[] {
  const out: string[] = [];

  if (isObject(expected) && isObject(actual)) {
    const keys = [...new Set([...Object.keys(expected), ...Object.keys(actual)])].sort();
    for (const key of keys) {
      const path = where ? `${where}.${key}` : key;
      if (!(key in actual)) {
        out.push(`  ${path}: expected ${JSON.stringify(expected[key])}, missing from output`);
      } else if (!(key in expected)) {
        out.push(`  ${path}: unexpected ${JSON.stringify(actual[key])} in output`);
      } else {
        out.push(...differences(expected[key], actual[key], path));
      }
    }
  } else if (Array.isArray(expected) && Array.isArray(actual)) {
    if (expected.length !== actual.length) {
      out.push(`  ${where}: expected ${expected.length} items, got ${actual.length}`);
    } else {
      expected.forEach((item, i) => out.push(...differences(item, actual[i], `${where}[${i}]`)));
    }
  } else if (JSON.stringify(expected) !== JSON.stringify(actual)) {
    out.push(`  ${where}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }

  return out;
}

describe("behavioural conformance", () => {
  it("the corpus is present on this stack too", () => {
    expect(inputs.length).toBeGreaterThanOrEqual(20);
    const expectedCount = readdirSync(EXPECTED_DIR).filter((f) => f.endsWith(".json")).length;
    expect(expectedCount).toBe(inputs.length);
  });

  for (const file of inputs) {
    it(basename(file, ".json"), () => {
      const result = parseSceneSpec(read(INPUT_DIR, file));
      if (!result.ok) {
        throw new Error(`zod rejected a valid fixture:\n${result.errors.join("\n")}`);
      }

      const actual = canonical(result.spec);
      const expected = read(EXPECTED_DIR, file);
      const diff = differences(expected, actual);

      if (diff.length > 0) {
        throw new Error(
          `${file}: zod output differs from the schema-derived expectation\n${diff.join("\n")}`,
        );
      }
      expect(actual).toEqual(expected);
    });
  }
});
