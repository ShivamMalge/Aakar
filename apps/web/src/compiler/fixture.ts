// Test fixtures. Kept out of *.test.ts so the compiler tests and the fuzz suite can
// share one definition of "a minimal valid spec".
import { SCHEMA_VERSION } from "../scenespec";
import type { Part, SceneSpec } from "../scenespec";

export function part(id: string, over: Partial<Part> = {}): Part {
  return {
    id,
    name: id,
    geometry: { type: "sphere", radius: 1 },
    material: { color: "#aabbcc", opacity: 1, roughness: 0.5 },
    clip_exempt: false,
    importance: "core",
    provenance: { chunk_ids: ["golden"] },
    ...over,
  } as Part;
}

export function spec(parts: Part[], over: Partial<SceneSpec> = {}): SceneSpec {
  return {
    schema_version: SCHEMA_VERSION,
    topic: "test_topic",
    title: "Test Topic",
    parts,
    ...over,
  } as SceneSpec;
}
