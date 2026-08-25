// Canonical form for a parsed SceneSpec — TypeScript side.
//
// The mirror of canonical.py. Verdict agreement is not behavioural agreement: before
// D-018, zod applied no geometry defaults while pydantic applied them all, and the
// verdict corpus could not see it because both stacks said "valid".
//
// Rules, identical on both sides:
//   1. object keys sorted lexicographically
//   2. keys whose value is null/undefined are dropped
//   3. an integral number is emitted as an integer; anything else rounds to 12 decimals
//   4. array order preserved

const DECIMALS = 12;
const FACTOR = 10 ** DECIMALS;

export function canonical(value: unknown): unknown {
  if (typeof value === "number") {
    const rounded = Math.round(value * FACTOR) / FACTOR;
    return Object.is(rounded, -0) ? 0 : rounded;
  }
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      const entry = (value as Record<string, unknown>)[key];
      if (entry === null || entry === undefined) continue;
      out[key] = canonical(entry);
    }
    return out;
  }
  return value;
}

export function dumps(value: unknown): string {
  return `${JSON.stringify(canonical(value), null, 2)}\n`;
}
