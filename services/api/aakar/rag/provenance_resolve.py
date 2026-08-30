"""Resolving ``unverified`` once chunk text exists (2C.6) — D-030's second half.

D-030 fixed the states and *when* each becomes knowable. Parse can only say ``none`` or
``unverified``. This is where a corpus exists, so ``unverified`` resolves:

* **strong** — at least one cited chunk names the part
* **weak** — chunks were retrieved, none of them names it

## ``source`` is a second axis, not more states (D-044)

Strength answers *does the chapter assert this?*; source answers *how reliably did we read
the chapter?* They are independent, and an OCR-derived strong match is genuinely different
from a digital one — OCR misreads are silent and produce plausible wrong words.

Collapsing them would multiply the enum to six and make "strong regardless of how we read
it" inexpressible, which is exactly the query the curation gate wants when ranking what a
human should check. So they are carried side by side and combined in exactly one place:
``display_confidence``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .index import Hit

ChunkSource = Literal["digital", "ocr", "mixed", "unknown"]
ResolvedStrength = Literal["none", "weak", "strong"]


def _names_part(text: str, terms: Sequence[str]) -> bool:
    """Does this chunk actually name the part?

    Whole-word, case-insensitive. Substring matching would count "iris" inside unrelated
    words, and a false positive here promotes a part to ``strong`` on evidence that never
    mentions it — which is the fabricated-confidence failure D-030 exists to prevent.
    """
    lowered = text.lower()
    return any(term and re.search(rf"\b{re.escape(term.lower())}\b", lowered) for term in terms)


def combine_sources(sources: Sequence[str]) -> ChunkSource:
    """``mixed`` when the supporting chunks disagree, rather than picking one arbitrarily."""
    distinct = {s for s in sources if s in {"digital", "ocr"}}
    if not distinct:
        return "unknown"
    if len(distinct) > 1:
        return "mixed"
    return "digital" if "digital" in distinct else "ocr"


@dataclass(frozen=True)
class ResolvedProvenance:
    """Two independent axes, carried together."""

    strength: ResolvedStrength
    source: ChunkSource
    #: Chunks that actually name the part — the evidence for ``strong``.
    naming_chunk_ids: tuple[str, ...] = ()
    #: Everything considered, whether it named the part or not.
    retrieved_chunk_ids: tuple[str, ...] = ()

    @property
    def display_confidence(self) -> str:
        """The one place the two axes combine, so callers do not each invent a rule.

        An OCR-derived strong match reads as ``strong (OCR)`` rather than silently as
        ``strong``: the claim is well supported, but every word of that support was read
        by a machine that fails quietly.
        """
        if self.strength == "none":
            return "not in your chapter"
        qualifier = {"ocr": " (OCR)", "mixed": " (partly OCR)"}.get(self.source, "")
        return f"{self.strength}{qualifier}"


def resolve(
    hits: Sequence[Hit],
    scope_terms: Sequence[str],
    *,
    cited_chunk_ids: Sequence[str] = (),
) -> ResolvedProvenance:
    """Resolve strength from real chunk text (D-030), reading source alongside it.

    ``cited_chunk_ids`` restricts the evidence to what a spec actually cited, when the
    caller has a spec part in hand. Empty means "judge on what retrieval found", which is
    the Q&A path.
    """
    allowed = set(cited_chunk_ids)
    considered = [h for h in hits if not allowed or h.chunk_id in allowed]
    if not considered:
        return ResolvedProvenance(strength="none", source="unknown")

    naming = [h for h in considered if _names_part(h.text, scope_terms)]
    strength: ResolvedStrength = "strong" if naming else "weak"

    # Source is read from the chunks carrying the claim: for `strong` that is the naming
    # chunks, since those are what the strength actually rests on.
    basis = naming or considered
    return ResolvedProvenance(
        strength=strength,
        source=combine_sources([h.source for h in basis]),
        naming_chunk_ids=tuple(h.chunk_id for h in naming),
        retrieved_chunk_ids=tuple(h.chunk_id for h in considered),
    )
