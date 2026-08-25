// Rejection tests for the three constraints JSON Schema cannot express. Phase 3 feeds
// these messages into the repair prompt (D3), so the assertions check the *text*, not
// just that something failed.
import { describe, expect, it } from "vitest";

import { part, spec } from "./fixture";
import { validateGraph } from "./validate";

const messages = (s: Parameters<typeof validateGraph>[0]): string =>
  validateGraph(s).map((e) => `${e.path}: ${e.message}`).join("\n");

describe("validateGraph", () => {
  it("accepts a well-formed tree", () => {
    expect(
      validateGraph(spec([part("eyeball"), part("lens", { parent_id: "eyeball" })])),
    ).toEqual([]);
  });

  it("rejects duplicate part ids and names where the first one was", () => {
    const out = messages(spec([part("lens"), part("cornea"), part("lens")]));
    expect(out).toContain("parts.2.id");
    expect(out).toContain('duplicate part id "lens"');
    expect(out).toContain("first used at parts.0");
  });

  it("rejects a parent that does not exist", () => {
    const out = messages(spec([part("lens", { parent_id: "nowhere" })]));
    expect(out).toContain("parts.0.parent_id");
    expect(out).toContain('references parent "nowhere"');
  });

  it("suggests a near-miss parent id", () => {
    const out = messages(spec([part("eyeball"), part("lens", { parent_id: "eyebal" })]));
    expect(out).toContain('did you mean "eyeball"?');
  });

  it("does not suggest an unrelated id", () => {
    const out = messages(spec([part("eyeball"), part("lens", { parent_id: "mitochondrion" })]));
    expect(out).not.toContain("did you mean");
  });

  it("rejects a part parented to itself", () => {
    const out = messages(spec([part("lens", { parent_id: "lens" })]));
    expect(out).toContain("is its own parent");
  });

  it("rejects a two-part cycle and names the loop", () => {
    const out = messages(
      spec([part("a", { parent_id: "b" }), part("b", { parent_id: "a" })]),
    );
    expect(out).toContain("parent cycle");
    expect(out).toMatch(/a -> b -> a|b -> a -> b/);
  });

  it("rejects a longer cycle", () => {
    const out = messages(
      spec([
        part("a", { parent_id: "c" }),
        part("b", { parent_id: "a" }),
        part("c", { parent_id: "b" }),
      ]),
    );
    expect(out).toContain("parent cycle");
  });

  it("reports a cycle once, not once per member", () => {
    const errs = validateGraph(
      spec([part("a", { parent_id: "b" }), part("b", { parent_id: "a" })]),
    ).filter((e) => e.message.includes("parent cycle"));
    expect(errs).toHaveLength(1);
  });

  it("reports every problem in one pass, not just the first", () => {
    const errs = validateGraph(
      spec([part("a"), part("a"), part("b", { parent_id: "ghost" })]),
    );
    expect(errs.length).toBeGreaterThanOrEqual(2);
  });

  it("does not hang on a cycle that dangles off a valid chain", () => {
    expect(() =>
      validateGraph(
        spec([
          part("root"),
          part("a", { parent_id: "root" }),
          part("x", { parent_id: "y" }),
          part("y", { parent_id: "x" }),
        ]),
      ),
    ).not.toThrow();
  });
});
