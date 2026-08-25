// The three constraints JSON Schema cannot express (schema `description` says so):
// unique part ids, parent_id resolving to a real part, and an acyclic parent graph.
//
// Error strings are a product surface, not a debug aid: Phase 3 feeds them straight
// into the repair prompt (D3), so each one names the offending path, states the rule,
// and where possible suggests the fix.
import type { SceneSpec } from "../scenespec";

export type SpecError = { path: string; message: string };

/** Levenshtein, capped — only used to suggest a near-miss id. */
function distance(a: string, b: string): number {
  const rows = a.length + 1;
  const cols = b.length + 1;
  let prev = Array.from({ length: cols }, (_, i) => i);
  for (let i = 1; i < rows; i++) {
    const curr = [i, ...Array<number>(cols - 1).fill(0)];
    for (let j = 1; j < cols; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min((curr[j - 1] ?? 0) + 1, (prev[j] ?? 0) + 1, (prev[j - 1] ?? 0) + cost);
    }
    prev = curr;
  }
  return prev[cols - 1] ?? 0;
}

function nearest(target: string, candidates: readonly string[]): string | undefined {
  let best: string | undefined;
  let bestScore = Infinity;
  for (const c of candidates) {
    const d = distance(target, c);
    if (d < bestScore) {
      bestScore = d;
      best = c;
    }
  }
  // Only suggest something genuinely close, or the hint is noise.
  return best !== undefined && bestScore <= Math.max(2, Math.floor(target.length / 3))
    ? best
    : undefined;
}

/**
 * Graph-level validation. Returns every error found rather than the first — a repair
 * round that fixes one problem per attempt burns the two-round budget (D3) on nothing.
 */
export function validateGraph(spec: SceneSpec): SpecError[] {
  const errors: SpecError[] = [];
  const firstIndexById = new Map<string, number>();

  spec.parts.forEach((part, i) => {
    const seen = firstIndexById.get(part.id);
    if (seen !== undefined) {
      errors.push({
        path: `parts.${i}.id`,
        message: `duplicate part id "${part.id}" — ids must be unique (first used at parts.${seen})`,
      });
      return;
    }
    firstIndexById.set(part.id, i);
  });

  const ids = [...firstIndexById.keys()];

  spec.parts.forEach((part, i) => {
    const parent = part.parent_id;
    if (parent === undefined) return;
    if (parent === part.id) {
      errors.push({
        path: `parts.${i}.parent_id`,
        message: `part "${part.id}" is its own parent — a part cannot contain itself`,
      });
      return;
    }
    if (!firstIndexById.has(parent)) {
      const hint = nearest(parent, ids);
      errors.push({
        path: `parts.${i}.parent_id`,
        message:
          `part "${part.id}" references parent "${parent}", which is not a part in this spec` +
          (hint !== undefined ? ` — did you mean "${hint}"?` : ""),
      });
    }
  });

  errors.push(...findCycles(spec, firstIndexById));
  return errors;
}

/** Iterative colour-marking DFS; reports the cycle it actually walked. */
function findCycles(spec: SceneSpec, indexById: ReadonlyMap<string, number>): SpecError[] {
  const parentOf = new Map<string, string>();
  for (const part of spec.parts) {
    // Only edges that resolve; unresolved parents are already reported above.
    if (part.parent_id !== undefined && indexById.has(part.parent_id)) {
      if (!parentOf.has(part.id)) parentOf.set(part.id, part.parent_id);
    }
  }

  const errors: SpecError[] = [];
  const state = new Map<string, "visiting" | "done">();
  const reported = new Set<string>();

  for (const start of parentOf.keys()) {
    if (state.get(start) === "done") continue;

    const stack: string[] = [];
    const onStack = new Set<string>();
    let node: string | undefined = start;

    while (node !== undefined && state.get(node) !== "done") {
      if (onStack.has(node)) {
        const cycle = [...stack.slice(stack.indexOf(node)), node];
        const key = [...cycle].sort().join("\u0000");
        if (!reported.has(key)) {
          reported.add(key);
          const at = indexById.get(node);
          errors.push({
            path: `parts.${at ?? 0}.parent_id`,
            message: `parent cycle: ${cycle.join(" -> ")} — the parent graph must be a tree`,
          });
        }
        break;
      }
      stack.push(node);
      onStack.add(node);
      state.set(node, "visiting");
      node = parentOf.get(node);
    }

    for (const seen of stack) state.set(seen, "done");
  }

  return errors;
}
