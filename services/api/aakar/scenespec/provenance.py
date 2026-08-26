"""Derived provenance strength (D-025, schema 1.2) — the shared contract, Python side.

The mirror of ``packages/scenespec/provenance.ts``.

``chunk_ids`` may be empty as of schema 1.2. Requiring at least one citation is safe for
hand-authored specs and unsafe for generated ones: a model proposing a part the chapter
does not mention is forced to cite the nearest plausible chunk, which makes fabricated
provenance mandatory — and that attacks the one claim this project rests on. Zero
provenance is now legal and meaningful.

Strength is DERIVED at parse, never author-supplied. ``provenance_strength`` is not a
schema property, so ``additionalProperties: false`` already rejects any attempt to set it.

**What is derivable here, and what is not.** The ruling defines *strong* as ">= 1 chunk
naming the part" and *weak* as "chunks retrieved but not naming it". Whether a chunk
*names* the part can only be settled against chunk text, and no corpus exists at parse. So
parse derives the document's own claim:

===========  ==========================================================
``none``     ``chunk_ids`` is empty
``weak``     ``chunk_ids`` non-empty, but no ``evidence`` quotation
``strong``   ``chunk_ids`` non-empty **and** ``evidence`` present
===========  ==========================================================

``evidence`` is defined in spec §4 as a quotation from the cited chunk, so its presence is
the document's assertion that a chunk names this part. D-008's validator checks that
quotation against real chunk text in Phase 3 and may **downgrade** strong to weak when it
does not match. Parse states the claim; the corpus check verifies it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

ProvenanceStrength = Literal["strong", "weak", "none"]

STRENGTHS: tuple[ProvenanceStrength, ...] = ("strong", "weak", "none")


def _unwrap(value: Any) -> Any:
    """datamodel-code-generator wraps constrained scalars in RootModel."""
    return getattr(value, "root", value)


def _parts(spec: Any) -> Sequence[Mapping[str, Any]]:
    raw = spec.get("parts") or [] if isinstance(spec, Mapping) else getattr(spec, "parts", []) or []
    out: list[Mapping[str, Any]] = []
    for part in raw:
        if isinstance(part, Mapping):
            out.append(part)
            continue
        provenance = getattr(part, "provenance", None)
        out.append(
            {
                "id": _unwrap(getattr(part, "id", None)),
                "provenance": {
                    "chunk_ids": [
                        _unwrap(c) for c in (getattr(provenance, "chunk_ids", None) or [])
                    ],
                    "evidence": _unwrap(getattr(provenance, "evidence", None)),
                },
            }
        )
    return out


def strength_of(part: Mapping[str, Any]) -> ProvenanceStrength:
    """Strength for one part, from the document alone."""
    provenance = part.get("provenance") or {}
    chunk_ids = provenance.get("chunk_ids") or []
    if len(chunk_ids) == 0:
        return "none"
    evidence = provenance.get("evidence")
    if isinstance(evidence, str) and evidence.strip():
        return "strong"
    return "weak"


def provenance_strengths(spec: Any) -> dict[str, ProvenanceStrength]:
    """Strength for every part, keyed by part id."""
    return {str(_unwrap(p.get("id"))): strength_of(p) for p in _parts(spec)}


def strength_counts(spec: Any) -> dict[ProvenanceStrength, int]:
    """How many parts sit at each strength — the curation gate's headline count."""
    counts: dict[ProvenanceStrength, int] = {"strong": 0, "weak": 0, "none": 0}
    for part in _parts(spec):
        counts[strength_of(part)] += 1
    return counts


def ungrounded_parts(spec: Any) -> list[str]:
    """Ids of parts nothing in the chapter asserts. The "no provenance" curation signal."""
    return [str(_unwrap(p.get("id"))) for p in _parts(spec) if strength_of(p) == "none"]
