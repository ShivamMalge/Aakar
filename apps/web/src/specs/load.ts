// Server-side loader for the hand-written Phase 1 specs (specs/golden, task 1.5).
//
// D-004 note: the real `/render/{topic_id}` resolves the **approved** row in
// `spec_versions`, and `?spec_version=` selects any row behind the owner session.
// Neither exists yet — Phase 1 has no database rows and makes no API call — so this
// loader serves the golden files and the route refuses `?spec_version=` outright
// rather than silently ignoring it.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, resolve } from "node:path";

import { type SceneSpec, parseSceneSpec } from "@/scenespec";

const GOLDEN_DIR = resolve(process.cwd(), "../../specs/golden");

export function goldenTopics(): string[] {
  if (!existsSync(GOLDEN_DIR)) return [];
  return readdirSync(GOLDEN_DIR)
    .filter((file) => file.endsWith(".json"))
    .map((file) => basename(file, ".json"))
    .sort();
}

export type LoadResult =
  | { ok: true; spec: SceneSpec }
  | { ok: false; reason: "not-found" }
  | { ok: false; reason: "invalid"; errors: string[] };

export function loadGoldenSpec(topic: string): LoadResult {
  // The topic segment reaches the filesystem, so it is matched against the known set
  // rather than interpolated into a path.
  if (!goldenTopics().includes(topic)) return { ok: false, reason: "not-found" };

  const raw: unknown = JSON.parse(readFileSync(resolve(GOLDEN_DIR, `${topic}.json`), "utf8"));
  const parsed = parseSceneSpec(raw);
  if (!parsed.ok) return { ok: false, reason: "invalid", errors: parsed.errors };
  return { ok: true, spec: parsed.spec };
}
