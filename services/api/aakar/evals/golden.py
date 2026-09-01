"""The golden provenance set (2D.1a) and a Qdrant-free ranker to run it against.

## The labels are PROPOSED until a human says otherwise

``questions.json`` ships with ``verified: false``. Every ``supported_by`` list in it was
proposed by this system, and a golden set labelled by the thing it evaluates measures
self-consistency, not accuracy. `load_golden_set` therefore refuses to hand back a set that
claims to be verified without a name attached, and marks everything it loads
``provisional`` while the flag is false. That flag rides through
`FaithfulnessReport.provisional` into the printed report, so a number cannot escape its
caveat by being copied out of a terminal.

## Why the ranker here, and not Qdrant

The eval scores *retrieval quality and citation faithfulness*. Neither is a property of the
storage engine: Qdrant contributes a cosine search over the same unit vectors this computes
directly. Running the golden set through an in-process ranker means the eval runs in CI with
no container, no key and no fixture teardown — and the numbers it produces are the numbers
the real path would produce, because the embedder and the distance metric are identical.

What this deliberately does **not** cover is Qdrant's own behaviour: payload filtering,
corpus isolation, collection width. Those have their own tests (`test_retrieval.py`), which
do need the container. Keeping the two apart means neither can quietly stand in for the
other.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from aakar.rag.index import Hit

#: `services/api/aakar/evals/golden.py` -> repo root -> `evals/golden-provenance`.
GOLDEN_DIR = Path(__file__).resolve().parents[4] / "evals" / "golden-provenance"


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    #: ``single_chunk`` | ``multi_chunk`` | ``not_in_chapter``
    kind: str
    question: str
    part: str
    aliases: tuple[str, ...]
    #: PROPOSED chunk ids. Meaningless as ground truth while the set is unverified.
    supported_by: tuple[str, ...]
    note: str = ""

    @property
    def answerable(self) -> bool:
        return self.kind != "not_in_chapter"


@dataclass(frozen=True)
class GoldenSet:
    chunks: tuple[Hit, ...]
    questions: tuple[GoldenQuestion, ...]
    verified: bool
    verified_by: str | None
    source: str
    #: The chapter's own SCOPE_LIMITS block. Carried rather than left in the file so the
    #: caveats travel with the numbers instead of waiting to be looked up.
    scope_limits: dict[str, str]

    @property
    def provisional(self) -> bool:
        """Unverified labels make every number derived from them provisional."""
        return not self.verified

    def by_id(self, chunk_id: str) -> Hit:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise KeyError(f"no chunk {chunk_id!r} in the golden set")

    @property
    def ocr_chunk_ids(self) -> tuple[str, ...]:
        """Chunks marked OCR — the ones D-044's display path has to treat differently."""
        return tuple(c.chunk_id for c in self.chunks if c.source == "ocr")


def load_golden_set(directory: Path | None = None, *, corpus_id: str = "golden") -> GoldenSet:
    """Load the chapter and questions, carrying the verification flag with them."""
    directory = directory or GOLDEN_DIR
    chapter = json.loads((directory / "chapter.json").read_text(encoding="utf-8"))
    questions = json.loads((directory / "questions.json").read_text(encoding="utf-8"))

    verified = bool(questions.get("verified", False))
    verified_by = questions.get("verified_by")
    if verified and not verified_by:
        # A set that claims verification without naming who did it is worse than an
        # unverified one: it looks like evidence and cannot be chased down.
        raise ValueError(
            "questions.json sets verified: true but verified_by is empty. A golden set with "
            "no one accountable for its labels is not verified."
        )

    chunks = tuple(
        Hit(
            chunk_id=str(c["id"]),
            corpus_id=corpus_id,
            document_id="golden-chapter",
            text=str(c["text"]),
            # The golden chapter came from HTML, so there is no PDF pagination behind it.
            # page_index is positional and page_label is what chapter.json asserts; see
            # PAGE_LABELS_ARE_PROPOSED there for why only the mechanism is under test here.
            page_index=i,
            page_label=str(c["page_label"]),
            section=c.get("section"),
            source=str(c.get("source", "digital")),
            score=0.0,
        )
        for i, c in enumerate(chapter["chunks"])
    )

    parsed = tuple(
        GoldenQuestion(
            id=str(q["id"]),
            kind=str(q["kind"]),
            question=str(q["question"]),
            part=str(q["part"]),
            aliases=tuple(q.get("aliases", ())),
            supported_by=tuple(q.get("supported_by", ())),
            note=str(q.get("note", "")),
        )
        for q in questions["questions"]
    )

    return GoldenSet(
        chunks=chunks,
        questions=parsed,
        verified=verified,
        verified_by=verified_by,
        source=str(chapter["source"]["work"]),
        scope_limits={str(k): str(v) for k, v in chapter.get("SCOPE_LIMITS", {}).items()},
    )


@dataclass(frozen=True)
class AnswerFixture:
    id: str
    question_id: str
    #: Chunk ids behind markers [1], [2], ... — fixed by the fixture, not by ranking.
    passages: tuple[str, ...]
    #: The count this fixture exists to trigger: a harness that stops seeing it is broken.
    expect: str
    text: str
    why: str = ""


def load_answers(directory: Path | None = None) -> tuple[AnswerFixture, ...]:
    directory = directory or GOLDEN_DIR
    payload = json.loads((directory / "answers.json").read_text(encoding="utf-8"))
    return tuple(
        AnswerFixture(
            id=str(a["id"]),
            question_id=str(a["question_id"]),
            passages=tuple(a["passages"]),
            expect=str(a["expect"]),
            text=str(a["text"]),
            why=str(a.get("why", "")),
        )
        for a in payload["answers"]
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product. Both sides are already L2-normalized (D-043's MRL rule), so this *is*
    cosine — and if that ever stops being true the eval numbers move, which is the loudest
    place for a missing normalization to show up."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def rank(
    query_vector: Sequence[float], chunks: Sequence[Hit], vectors: Sequence[Sequence[float]]
) -> list[Hit]:
    """Score every chunk and return them best-first, with the score attached."""
    scored = [
        Hit(**{**chunk.__dict__, "score": cosine(query_vector, vector)})
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    return sorted(scored, key=lambda h: h.score, reverse=True)
