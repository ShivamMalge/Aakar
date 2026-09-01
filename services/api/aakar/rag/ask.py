"""The `/ask` pipeline (2C.4, 2C.5).

**The order is the design.** Each step is cheaper than the next and can end the request:

    1. grant check     -- owner may reach this corpus at all (D-029)
    2. cache lookup    -- FREE. Must come before quota and budget.
    3. per-owner quota -- one user cannot drain everyone else (2B.10)
    4. global budget   -- the operator's total bill (D8)
    5. retrieval       -- part-scoped, with a floor (2C.2/2C.3)
    6. answer tier     -- the only step that spends (2B.8)

**A cache hit must never consume quota or budget**, so the lookup sits above both. Putting
quota first would charge a student for an answer that cost nothing, which penalises exactly
the behaviour the cache exists to encourage — and would make the measured hit rate a lie,
since a "hit" would still count against them.

**Citations render the page LABEL, never the index** (2A.6). `Citation.render` is the only
thing that formats one, so there is a single place that could ever get it wrong.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, cast, get_args

from qdrant_client import QdrantClient

from aakar.ingest.corpus import can_read
from aakar.providers import BudgetExceeded, CostLedger

from . import cache
from .embedding import Embedder
from .provenance_resolve import (
    ResolvedProvenance,
    ResolvedStrength,
    combine_sources,
    resolve,
)
from .quota import OwnerQuota, QuotaExceeded, check_owner_quota
from .retrieval import Retrieval, retrieve
from .tiers import Tier

AnswerKind = Literal["cached", "generated", "not_in_chapter", "no_provenance"]


class NotPermitted(RuntimeError):
    """The owner holds no grant for this corpus. Distinct from "nothing was found"."""


@dataclass(frozen=True)
class Citation:
    """A page reference. Carries both spaces; renders only the label."""

    chunk_id: str
    page_index: int
    page_label: str
    source: str

    def render(self) -> str:
        """``[p. vii]``, or ``[p. vii, scanned]`` for OCR — the LABEL (2A.6, D6, D-044).

        The index is carried for addressing and deliberately never rendered: a citation to
        "page 3" that means the third PDF page is wrong when the book calls it "vii", and
        wrong in a way the reader cannot detect.

        **OCR is marked here, per citation, not only on the answer.** An answer-level
        confidence covers the answer; a student checking one page needs to know whether
        *that* page was read by a machine. When four citations are digital and one is
        scanned, an answer-level qualifier tells them something is uncertain but not which
        page to distrust — and OCR misreads are silent and produce plausible wrong words,
        so "which one" is the entire question.
        """
        return (
            f"[p. {self.page_label}, scanned]"
            if self.source == "ocr"
            else (f"[p. {self.page_label}]")
        )


@dataclass(frozen=True)
class Answer:
    kind: AnswerKind
    text: str
    citations: tuple[Citation, ...] = ()
    provenance: ResolvedProvenance | None = None
    #: True when served from cache — no quota consumed, no money spent.
    from_cache: bool = False
    #: Set when the cached question was a paraphrase, so the panel can say so (D4).
    similar_question: str | None = None
    retrieval: Retrieval | None = field(default=None, repr=False)

    @property
    def cited_pages(self) -> tuple[str, ...]:
        return tuple(c.page_label for c in self.citations)

    @property
    def display_confidence(self) -> str:
        """What the panel shows (D-044). Never plain ``strong`` over a scanned page.

        `ResolvedProvenance.display_confidence` reads its source axis from the chunks that
        *name the part* — the evidence the strength rests on. What the student is shown is
        every retrieved citation, which is a superset. So an answer can rest on digital
        evidence and still put a scanned page in front of someone, and reading the
        evidence-axis value straight out would describe that answer as ``strong`` with no
        hint that one of its pages came out of an OCR engine.

        Evidence that is wholly OCR keeps ``(OCR)`` rather than being softened to
        ``(partly OCR)`` by digital pages that happen to be alongside it: the claim still
        rests entirely on machine-read text. Otherwise the shown citations decide. So this
        can only ever make a confidence more cautious, never less.
        """
        if self.provenance is None:
            return "unknown"
        if not self.citations or self.provenance.source == "ocr":
            return self.provenance.display_confidence
        shown = combine_sources([c.source for c in self.citations])
        return replace(self.provenance, source=shown).display_confidence

    @property
    def scanned_pages(self) -> tuple[str, ...]:
        """Page labels the student is being shown that were read by OCR."""
        return tuple(c.page_label for c in self.citations if c.source == "ocr")


def _citations(retrieval: Retrieval) -> tuple[Citation, ...]:
    return tuple(
        Citation(
            chunk_id=hit.chunk_id,
            page_index=hit.page_index,
            page_label=hit.page_label,
            source=hit.source,
        )
        for hit in retrieval.hits
    )


def ask(
    conn: sqlite3.Connection,
    qdrant: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
    corpus_id: str,
    topic_id: str,
    question: str,
    part_id: str,
    name: str,
    aliases: Sequence[str] = (),
    instance_of: str | None = None,
    part_chunk_ids: Sequence[str] = (),
    ledger: CostLedger | None = None,
    quota: OwnerQuota | None = None,
    generate: Callable[[str, Retrieval], str] | None = None,
) -> Answer:
    """Answer one question about one part. See the module docstring for why this order.

    `generate` is injected rather than imported so the answer tier can be driven by a stub
    in replay; a missing one means the caller wants everything except the model call.
    """
    if not can_read(conn, owner_id, corpus_id):
        raise NotPermitted(f"owner holds no grant for corpus {corpus_id}")

    scope = cache.scope_key(part_id, instance_of)

    # --- 2. cache: FREE, so it comes before quota and budget --------------------
    question_vector = embedder.embed_one(question)
    hit = cache.lookup(conn, corpus_id=corpus_id, scope=scope, question_vector=question_vector)
    if hit is not None:
        # Rebuilt field by field rather than by `Citation(**c)`: the cached payload is
        # JSON from the database, so its shape is a runtime fact, and splatting it would
        # turn a schema change into a TypeError at answer time.
        stored = hit.answer.get("citations")
        citations = tuple(
            Citation(
                chunk_id=str(c["chunk_id"]),
                page_index=int(c["page_index"]),
                page_label=str(c["page_label"]),
                source=str(c["source"]),
            )
            for c in (stored if isinstance(stored, list) else [])
        )
        # Strength is stored with the answer so a cached one keeps its confidence. Without
        # it the same answer reads as `strong (OCR)` when generated and `unknown` when
        # served from cache — the OCR warning would survive exactly until the answer became
        # popular enough for a second student to ask. Source is re-derived from the stored
        # citations rather than persisted, so it cannot drift out of step with them.
        cached_provenance: ResolvedProvenance | None = None
        stored_strength = str(hit.answer.get("strength", ""))
        if stored_strength in get_args(ResolvedStrength):
            cached_provenance = ResolvedProvenance(
                strength=cast(ResolvedStrength, stored_strength),
                source=combine_sources([c.source for c in citations]),
            )
        return Answer(
            kind="cached",
            text=str(hit.answer.get("text", "")),
            citations=citations,
            provenance=cached_provenance,
            from_cache=True,
            similar_question=hit.question if hit.is_paraphrase else None,
        )

    # --- 3 & 4. two separate checks, both must pass -----------------------------
    check_owner_quota(conn, owner_id, quota)
    if ledger is not None:
        ledger.preflight(0.0)  # the provider charges its own estimate before the call

    # --- 5. retrieval, with the floor -------------------------------------------
    found = retrieve(
        qdrant,
        embedder,
        corpus_id=corpus_id,
        question=question,
        name=name,
        aliases=aliases,
        instance_of=instance_of,
    )
    provenance = resolve(found.hits, found.terms, cited_chunk_ids=part_chunk_ids)

    if not found.covered:
        # A first-class result (Rule 6), not an error and not an empty state. No citations,
        # because there is nothing to cite — and no model call, because there is nothing
        # to ground an answer in.
        return Answer(
            kind="not_in_chapter",
            text=(
                f"Your chapter does not appear to cover {found.scope}. "
                "Nothing in the uploaded material matched this question closely enough "
                "to answer from."
            ),
            provenance=ResolvedProvenance(strength="none", source="unknown"),
            retrieval=found,
        )

    if provenance.strength == "none":
        return Answer(
            kind="no_provenance",
            text=(
                f"Nothing in your chapter asserts that {found.scope} exists, so there is "
                "nothing here to cite."
            ),
            provenance=provenance,
            retrieval=found,
        )

    # --- 6. the only step that spends -------------------------------------------
    citations = _citations(found)
    if generate is None:
        text = "\n".join(f"{hit.text} [p. {hit.page_label}]" for hit in found.hits[:3])
    else:
        text = generate(question, found)

    answer = Answer(
        kind="generated",
        text=text,
        citations=citations,
        provenance=provenance,
        retrieval=found,
    )

    cache.store(
        conn,
        owner_id=owner_id,
        corpus_id=corpus_id,
        topic_id=topic_id,
        scope=scope,
        question=question,
        question_vector=question_vector,
        answer={
            "text": answer.text,
            "citations": [c.__dict__ for c in citations],
            # See the cache-hit branch: without this a popular answer silently loses its
            # provenance the moment it starts being served from cache.
            "strength": provenance.strength,
        },
    )
    return answer


__all__ = [
    "Answer",
    "AnswerKind",
    "BudgetExceeded",
    "Citation",
    "NotPermitted",
    "QuotaExceeded",
    "Tier",
    "ask",
]
