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

// specs/golden is the Phase 1 deliverable (exactly three hand-written topics);
// specs/stress holds synthetic fixtures that must render but are not part of that set.
const SPEC_DIRS = [
  resolve(process.cwd(), "../../specs/golden"),
  resolve(process.cwd(), "../../specs/stress"),
];

function specFiles(): Map<string, string> {
  const found = new Map<string, string>();
  for (const dir of SPEC_DIRS) {
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
      found.set(basename(file, ".json"), resolve(dir, file));
    }
  }
  return found;
}

export function goldenTopics(): string[] {
  return [...specFiles().keys()].sort();
}

export type LoadResult =
  | { ok: true; spec: SceneSpec }
  | { ok: false; reason: "not-found" }
  | { ok: false; reason: "invalid"; errors: string[] };

export function loadGoldenSpec(topic: string): LoadResult {
  // The topic segment reaches the filesystem, so it is resolved through the known set
  // rather than interpolated into a path.
  const path = specFiles().get(topic);
  if (path === undefined) return { ok: false, reason: "not-found" };

  const raw: unknown = JSON.parse(readFileSync(path, "utf8"));
  const parsed = parseSceneSpec(raw);
  if (!parsed.ok) return { ok: false, reason: "invalid", errors: parsed.errors };
  return { ok: true, spec: parsed.spec };
}
