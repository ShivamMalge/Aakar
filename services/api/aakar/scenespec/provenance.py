"""Provenance strength (D-025, refined by D-030) — the shared contract, Python side.

The mirror of ``packages/scenespec/provenance.ts``.

``chunk_ids`` may be empty as of schema 1.2: requiring a citation forced a model with
nothing to cite to cite the nearest plausible chunk, which made fabricated provenance
mandatory.

**The uncertainty is in the type, not in a comment.** An earlier draft derived ``strong``
at parse from the presence of an ``evidence`` quotation, on the grounds that Phase 3 would
downgrade it later. That was wrong in exactly the way this field exists to prevent: a
field named ``provenance_strength`` reading "strong" when nothing has read the chunk text
is fabricated confidence, and every consumer between parse and that check sees an unearned
claim.

Four states, and *when* each becomes knowable is part of the contract:

============  ==========  =============================================================
state         knowable    meaning
============  ==========  =============================================================
``none``      parse       ``chunk_ids`` is empty; nothing in the chapter is cited
``unverified``  parse     ``chunk_ids`` is non-empty; the text has not been examined
``weak``      2B/3        chunks were retrieved but none of them names the part
``strong``    2B/3        at least one cited chunk names the part
============  ==========  =============================================================

:func:`parse_time_strength` can only return the first two, and :func:`assert_parse_time`
makes emitting either of the others a validation error rather than a convention. The
distinction is a real product one too: "we checked and found nothing" and "we have not
checked" are different things to show a student.

Strength is DERIVED, never author-supplied. It is not a schema property, so
``additionalProperties: false`` already rejects any attempt to set it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

ProvenanceStrength = Literal["none", "unverified", "weak", "strong"]
ParseTimeStrength = Literal["none", "unverified"]
ResolvedStrength = Literal["weak", "strong"]

#: Everything parse is allowed to emit.
PARSE_TIME_STRENGTHS: tuple[ProvenanceStrength, ...] = ("none", "unverified")
#: Only reachable once corpus text exists (Phase 2B/3).
RESOLVED_STRENGTHS: tuple[ProvenanceStrength, ...] = ("weak", "strong")


def is_parse_time_strength(value: str) -> bool:
    return value in PARSE_TIME_STRENGTHS


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
                },
            }
        )
    return out


def parse_time_strength(part: Mapping[str, Any]) -> ParseTimeStrength:
    """Strength for one part, from the document alone.

    Note what is deliberately NOT consulted: ``evidence``. A quotation the author supplied
    is still the author's claim about a chunk nobody has read. It becomes evidence of
    anything only once D-008's check compares it against the cited chunk's real text.
    """
    provenance = part.get("provenance") or {}
    chunk_ids = provenance.get("chunk_ids") or []
    return "unverified" if len(chunk_ids) > 0 else "none"


def provenance_strengths(spec: Any) -> dict[str, ParseTimeStrength]:
    """Strength for every part, keyed by part id."""
    return {str(_unwrap(p.get("id"))): parse_time_strength(p) for p in _parts(spec)}


def assert_parse_time(strengths: Mapping[str, str]) -> list[tuple[str, str]]:
    """Guards the boundary: parse must never claim a verified strength.

    Returns the offending ``(part_id, strength)`` pairs so the caller can turn them into
    parse issues. Typing alone would not catch a value arriving from JSON, from storage,
    or from a future code path that resolves strength too early.
    """
    return [
        (part_id, strength)
        for part_id, strength in strengths.items()
        if not is_parse_time_strength(strength)
    ]


def strength_counts(spec: Any) -> dict[ParseTimeStrength, int]:
    """How many parts sit at each strength — the curation gate's headline count."""
    counts: dict[ParseTimeStrength, int] = {"none": 0, "unverified": 0}
    for part in _parts(spec):
        counts[parse_time_strength(part)] += 1
    return counts


def ungrounded_parts(spec: Any) -> list[str]:
    """Ids of parts nothing in the chapter cites. The "no provenance" curation signal."""
    return [str(_unwrap(p.get("id"))) for p in _parts(spec) if parse_time_strength(p) == "none"]
