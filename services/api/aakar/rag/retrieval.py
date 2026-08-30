"""Part-scoped retrieval and the relevance floor (2C.2, 2C.3).

## The scope key

Name + aliases, or ``instance_of`` where present. Parts sharing an ``instance_of`` are
**one retrieval target** (D-022): an animal cell's two mitochondria are the same structure
asked about twice, and scoping them separately would split one concept's evidence in half.

## The floor is a first-class result, not an error

Below the floor the answer is **"your chapter does not cover this"** — a real answer with a
real UI state (spec §6, Rule 6). It is not an exception, not an empty list the caller has to
interpret, and emphatically not a prompt to the model to answer anyway. ``Retrieval.covered``
makes the distinction impossible to skip: a caller that ignores it gets an empty ``hits``
list and would generate from nothing, which is the fabrication Rule 6 exists to prevent.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import QdrantClient

from .embedding import Embedder
from .index import Hit, search

#: Below this best-score, the chapter does not cover the question.
#:
#: Conservative for the same reason as the cache threshold (D-041): answering from thin
#: evidence produces a fluent, cited, wrong answer, while refusing produces a true one the
#: student can act on. Config, because it must be re-measured against the real embedder.
DEFAULT_FLOOR = 0.35


def relevance_floor() -> float:
    return float(os.environ.get("AAKAR_RELEVANCE_FLOOR", DEFAULT_FLOOR))


def part_scope_terms(
    name: str, aliases: Sequence[str] = (), instance_of: str | None = None
) -> list[str]:
    """The terms that define this part's retrieval scope (D5, D-022).

    ``instance_of`` replaces the part's own name when present — it is the concept the
    chapter talks about, while the part id is an implementation detail of the model.
    """
    head = instance_of or name
    seen: set[str] = set()
    out: list[str] = []
    for term in (head, *aliases):
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(term.strip())
    return out


@dataclass(frozen=True)
class Retrieval:
    """What retrieval found, and whether it is enough to answer from."""

    scope: str
    terms: tuple[str, ...]
    hits: tuple[Hit, ...]
    floor: float

    @property
    def best_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0

    @property
    def covered(self) -> bool:
        """False means "your chapter does not cover this" — an answer, not a failure."""
        return bool(self.hits) and self.best_score >= self.floor

    @property
    def sources(self) -> set[str]:
        """``digital`` / ``ocr`` across the supporting chunks (D-044)."""
        return {hit.source for hit in self.hits}


def retrieve(
    qdrant: QdrantClient,
    embedder: Embedder,
    *,
    corpus_id: str,
    question: str,
    name: str,
    aliases: Sequence[str] = (),
    instance_of: str | None = None,
    limit: int = 8,
    floor: float | None = None,
) -> Retrieval:
    """Retrieve for one part scope.

    The query is the question **plus the scope terms**: a bare question like "what does it
    do" carries no signal about which part is meant, and the scope is exactly what the
    click already told us.
    """
    terms = part_scope_terms(name, aliases, instance_of)
    scoped_query = f"{' '.join(terms)} {question}"

    hits = search(
        qdrant,
        corpus_id=corpus_id,
        query_vector=embedder.embed_one(scoped_query),
        limit=limit,
    )
    return Retrieval(
        scope=instance_of or name,
        terms=tuple(terms),
        hits=tuple(hits),
        floor=relevance_floor() if floor is None else floor,
    )
