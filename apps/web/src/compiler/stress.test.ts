// Stress fixture (Phase 1 review, item 5).
//
// The largest golden spec is 13 parts at depth 4; the schema permits 40. Nothing had
// exercised the cap, and Phase 3 generates against it routinely. specs/stress/neuron.json
// is 40 parts at depth 6 covering all nine geometry types.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { parseSceneSpec, type SceneSpec } from "../scenespec";

import { compile } from "./compile";
import { applyClipping, clipPlaneFor } from "./cutaway";
import { applyExplode, planExplode } from "./explode";

const STRESS = resolve(__dirname, "../../../../specs/stress/neuron.json");
const raw: unknown = JSON.parse(readFileSync(STRESS, "utf8"));

function parsed(): SceneSpec {
  const result = parseSceneSpec(raw);
  if (!result.ok) throw new Error(result.errors.join("\n"));
  return result.spec;
}

function depthOf(spec: SceneSpec): number {
  const parentOf = new Map(spec.parts.map((p) => [p.id, p.parent_id]));
  let deepest = 0;
  for (const part of spec.parts) {
    let depth = 0;
    let node = parentOf.get(part.id);
    while (node !== undefined) {
      depth += 1;
      node = parentOf.get(node);
    }
    deepest = Math.max(deepest, depth);
  }
  return deepest;
}

describe("stress fixture: neuron", () => {
  it("is exactly at the schema's part cap", () => {
    expect(parsed().parts).toHaveLength(40);
  });

  it("nests at least six deep", () => {
    expect(depthOf(parsed())).toBeGreaterThanOrEqual(6);
  });

  it("exercises all nine geometry types", () => {
    const types = new Set(parsed().parts.map((p) => p.geometry.type));
    expect(types.size).toBe(9);
  });

  it("carries instance_of groups, so repeated structures share one retrieval target", () => {
    const groups = new Map<string, string[]>();
    for (const part of parsed().parts) {
      if (part.instance_of === undefined) continue;
      groups.set(part.instance_of, [...(groups.get(part.instance_of) ?? []), part.id]);
    }
    const shared = [...groups.values()].filter((ids) => ids.length > 1);
    expect(shared.length).toBeGreaterThanOrEqual(1);
    // Ruling B: parts sharing an instance_of are one target, and may share a name.
    for (const ids of shared) expect(ids.length).toBeGreaterThan(1);
  });

  it("has at least one clip_exempt part", () => {
    expect(parsed().parts.filter((p) => p.clip_exempt === true).length).toBeGreaterThanOrEqual(1);
  });

  it("mixes provenance strength", () => {
    const parts = parsed().parts;
    const withEvidence = parts.filter((p) => p.provenance.evidence !== undefined);
    const withoutEvidence = parts.filter((p) => p.provenance.evidence === undefined);
    expect(withEvidence.length).toBeGreaterThan(0);
    expect(withoutEvidence.length).toBeGreaterThan(0);
    // The schema requires >= 1 chunk id, so "no provenance at all" is not expressible.
    for (const part of parts) expect(part.provenance.chunk_ids.length).toBeGreaterThan(0);
  });

  it("compiles, explodes and clips without going non-finite", () => {
    const spec = parsed();
    const result = compile(spec);
    if (!result.ok) throw new Error(JSON.stringify(result.errors, null, 2));
    const { scene } = result;

    expect(scene.parts.size).toBe(40);

    applyClipping(scene, clipPlaneFor(spec));
    for (const mode of ["top-level", "per-part"] as const) {
      const plan = planExplode(scene, mode);
      for (const factor of [0, 0.5, 1]) {
        applyExplode(scene, plan, factor);
        for (const [id, { mesh }] of scene.parts) {
          const world = mesh.getWorldPosition(new THREE.Vector3());
          expect(world.toArray().every(Number.isFinite), `${id} went non-finite`).toBe(true);
        }
      }
    }
    scene.dispose();
  });

  it("reports timings", () => {
    const runs = 20;
    const spec = parsed();

    const t0 = performance.now();
    for (let i = 0; i < runs; i++) parseSceneSpec(raw);
    const parseMs = (performance.now() - t0) / runs;

    const t1 = performance.now();
    const scenes = [];
    for (let i = 0; i < runs; i++) {
      const r = compile(spec);
      if (!r.ok) throw new Error("compile failed");
      scenes.push(r.scene);
    }
    const compileMs = (performance.now() - t1) / runs;

    const scene = scenes[0]!;
    const t2 = performance.now();
    for (let i = 0; i < runs; i++) applyExplode(scene, planExplode(scene, "top-level"), 1);
    const explodeMs = (performance.now() - t2) / runs;

    const t3 = performance.now();
    for (let i = 0; i < runs; i++) applyClipping(scene, clipPlaneFor(spec));
    const clipMs = (performance.now() - t3) / runs;

    console.log(
      `\n  neuron (40 parts, depth 6), mean of ${runs} runs:\n` +
        `    parse + referential : ${parseMs.toFixed(2)} ms\n` +
        `    compile             : ${compileMs.toFixed(2)} ms\n` +
        `    explode (plan+apply): ${explodeMs.toFixed(2)} ms\n` +
        `    cutaway             : ${clipMs.toFixed(2)} ms`,
    );

    for (const s of scenes) s.dispose();
    // Generous: this is a regression tripwire, not a benchmark.
    expect(compileMs).toBeLessThan(500);
  });
});
