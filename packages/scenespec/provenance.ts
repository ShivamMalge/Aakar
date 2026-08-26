// Derived provenance strength (D-025, schema 1.2) — the shared contract, TypeScript side.
//
// `chunk_ids` may be empty as of schema 1.2. Requiring at least one citation is safe for
// hand-authored specs and unsafe for generated ones: a model proposing a part the chapter
// does not mention is forced to cite the nearest plausible chunk, which makes fabricated
// provenance mandatory. Zero provenance is now legal and meaningful — "this part exists in
// the model and nothing in the student's chapter asserts it".
//
// Strength is DERIVED at parse, never author-supplied. `provenance_strength` is not a
// schema property, so `additionalProperties: false` already rejects any attempt to set it.
//
// WHAT IS DERIVABLE HERE, AND WHAT IS NOT
//
// The ruling defines strong as ">= 1 chunk naming the part" and weak as "chunks retrieved
// but not naming it". Whether a chunk *names* the part can only be settled against chunk
// text, and no corpus exists at parse. So parse derives the document's own CLAIM:
//
//   none    chunk_ids is empty
//   weak    chunk_ids non-empty, but no `evidence` quotation
//   strong  chunk_ids non-empty AND `evidence` present
//
// `evidence` is defined in spec §4 as a quotation from the cited chunk, so its presence is
// the document's assertion that a chunk names this part. D-008's validator checks that
// quotation against the real chunk text in Phase 3 and may DOWNGRADE strong to weak when it
// does not match. Parse states the claim; the corpus check verifies it.
//
// The Python mirror is services/api/aakar/scenespec/provenance.py, and both are driven by
// packages/scenespec/fixtures/provenance/.

export type ProvenanceStrength = "strong" | "weak" | "none";

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

/** Strength for one part, from the document alone. */
export function strengthOf(part: ProvenancePartLike): ProvenanceStrength {
  const cited = part.provenance.chunk_ids.length > 0;
  if (!cited) return "none";
  const evidence = part.provenance.evidence;
  return evidence !== undefined && evidence.trim().length > 0 ? "strong" : "weak";
}

/** Strength for every part, keyed by part id. */
export function provenanceStrengths(
  spec: ProvenanceSpecLike,
): Record<string, ProvenanceStrength> {
  const out: Record<string, ProvenanceStrength> = {};
  for (const part of spec.parts) out[part.id] = strengthOf(part);
  return out;
}

/** How many parts sit at each strength — the curation gate's headline count. */
export function strengthCounts(
  spec: ProvenanceSpecLike,
): Record<ProvenanceStrength, number> {
  const counts: Record<ProvenanceStrength, number> = { strong: 0, weak: 0, none: 0 };
  for (const part of spec.parts) counts[strengthOf(part)] += 1;
  return counts;
}

/** Ids of parts nothing in the chapter asserts. The "no provenance" curation signal. */
export function ungroundedParts(spec: ProvenanceSpecLike): string[] {
  return spec.parts.filter((part) => strengthOf(part) === "none").map((part) => part.id);
}
