// Provenance strength (D-025, refined by D-030) — the shared contract, TypeScript side.
//
// `chunk_ids` may be empty as of schema 1.2. Requiring at least one citation is safe for
// hand-authored specs and unsafe for generated ones: a model proposing a part the chapter
// does not mention is forced to cite the nearest plausible chunk, which makes fabricated
// provenance mandatory. Zero provenance is legal and meaningful.
//
// THE UNCERTAINTY IS IN THE TYPE, NOT IN A COMMENT
//
// An earlier draft derived `strong` at parse from the presence of an `evidence` quotation,
// on the grounds that Phase 3 would later downgrade it. That was wrong in exactly the way
// this field exists to prevent: a field named `provenance_strength` reading "strong" when
// nothing has read the chunk text is fabricated confidence, and every consumer between
// parse and that check sees an unearned claim.
//
// So there are four states, and WHEN each becomes knowable is part of the contract:
//
//   parse time — structural, needs no corpus:
//     none        chunk_ids is empty; nothing in the chapter is cited at all
//     unverified  chunk_ids is non-empty; the text has not been examined
//
//   Phase 2B/3 — needs corpus text, resolves `unverified`:
//     weak        chunks were retrieved but none of them names the part
//     strong      at least one cited chunk names the part
//
// `parseTimeStrength` can only return the first two, and `assertParseTime` makes emitting
// either of the others a validation error rather than a convention. The distinction is
// also a real product one: "we checked and found nothing" and "we have not checked" are
// different things to show a student.
//
// Strength is DERIVED, never author-supplied. It is not a schema property, so
// `additionalProperties: false` already rejects any attempt to set it.
//
// The Python mirror is services/api/aakar/scenespec/provenance.py.

/** Every state the field can hold, across its whole lifecycle. */
export type ProvenanceStrength = "none" | "unverified" | "weak" | "strong";

/** The subset derivable without corpus text. Parse may emit nothing else. */
export type ParseTimeStrength = "none" | "unverified";

/** Resolved only once chunk text exists (Phase 2B/3). */
export type ResolvedStrength = "weak" | "strong";

export const PARSE_TIME_STRENGTHS: readonly ProvenanceStrength[] = ["none", "unverified"];
export const RESOLVED_STRENGTHS: readonly ProvenanceStrength[] = ["weak", "strong"];

export function isParseTimeStrength(value: string): value is ParseTimeStrength {
  return value === "none" || value === "unverified";
}

export type ProvenancePartLike = {
  id: string;
  provenance: {
    chunk_ids: readonly string[];
    evidence?: string | undefined;
  };
};

export type ProvenanceSpecLike = {
  parts: readonly ProvenancePartLike[];
};

/**
 * Strength for one part, from the document alone.
 *
 * Note what is deliberately NOT consulted: `evidence`. A quotation the author supplied is
 * still the author's claim about a chunk nobody has read. It becomes evidence of anything
 * only once D-008's check compares it against the cited chunk's real text.
 */
export function parseTimeStrength(part: ProvenancePartLike): ParseTimeStrength {
  return part.provenance.chunk_ids.length > 0 ? "unverified" : "none";
}

/** Strength for every part, keyed by part id. */
export function provenanceStrengths(
  spec: ProvenanceSpecLike,
): Record<string, ParseTimeStrength> {
  const out: Record<string, ParseTimeStrength> = {};
  for (const part of spec.parts) out[part.id] = parseTimeStrength(part);
  return out;
}

/**
 * Guards the boundary: parse must never claim a verified strength.
 *
 * Returns the ids that violate it, so the caller can turn them into parse issues. Typing
 * alone would not catch a value arriving from JSON, storage, or a future code path that
 * resolves strength too early.
 */
export function assertParseTime(
  strengths: Record<string, string>,
): Array<{ partId: string; strength: string }> {
  return Object.entries(strengths)
    .filter(([, strength]) => !isParseTimeStrength(strength))
    .map(([partId, strength]) => ({ partId, strength }));
}

/** How many parts sit at each strength — the curation gate's headline count. */
export function strengthCounts(
  spec: ProvenanceSpecLike,
): Record<ParseTimeStrength, number> {
  const counts: Record<ParseTimeStrength, number> = { none: 0, unverified: 0 };
  for (const part of spec.parts) counts[parseTimeStrength(part)] += 1;
  return counts;
}

/** Ids of parts nothing in the chapter cites. The "no provenance" curation signal. */
export function ungroundedParts(spec: ProvenanceSpecLike): string[] {
  return spec.parts.filter((part) => parseTimeStrength(part) === "none").map((part) => part.id);
}
