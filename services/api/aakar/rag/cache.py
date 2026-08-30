"""Semantic answer cache (2B.9).

Keyed on **(corpus_id, part scope, question embedding)**. A hit needs all three: the same
corpus, the same part scope, and a question close enough in embedding space.

## The scope key is `instance_of`, not the part id

Parts sharing an `instance_of` are one retrieval target (D-022), so they are **one cache
scope**. An animal cell's two mitochondria answer the same question with the same text from
the same chunks; giving them separate cache entries would double the cost of an identical
answer and let the two drift apart, which is worse than the cost.

## The threshold, and why correctness binds it

Default **0.92**, from D4. It is a *floor on similarity*, and the failure it guards is
specific: a permissive threshold buys hit rate by answering a question the student did not
ask. That is not a cheaper answer, it is a wrong one — and it is invisible, because the
answer is fluent, cited, and about the right part.

So the threshold is calibrated against **two** numbers, not one (G-03): the hit rate on a
paraphrase set that *should* hit, and the false-hit count on a near-miss set that *should
not*. `benchmark.py` measures both. Hit rate alone is trivially maximised by lowering the
threshold to zero, which is why the amendment says correctness is the binding constraint.

## Isolation

Cross-corpus isolation is structural, not a filter someone remembers to apply: `corpus_id`
is part of the key, so a question answered against corpus A cannot return for corpus B
(D-007). The test asserting that is the one that matters, because the failure mode is
serving one student's chapter text to another.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from aakar.db import new_id

#: D4's default. Calibrated against hit rate AND false-hit count, never hit rate alone.
DEFAULT_THRESHOLD = 0.92

Vector = Sequence[float]


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity. Returns 0.0 for a zero vector rather than dividing by zero."""
    if len(a) != len(b):
        raise ValueError(f"vectors differ in length: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def scope_key(part_id: str, instance_of: str | None) -> str:
    """The cache scope for a part.

    `instance_of` when present, so parts sharing a concept share their answers (D-022);
    the part id otherwise. Two mitochondria are one scope; a nucleus and a nucleolus are
    not.
    """
    return instance_of if instance_of else part_id


@dataclass(frozen=True)
class CachedAnswer:
    id: str
    question: str
    answer: dict[str, object]
    similarity: float

    @property
    def is_paraphrase(self) -> bool:
        """True when the cached question was not asked verbatim.

        D4 requires the panel to say "similar question" rather than pretend the student's
        exact words were answered.
        """
        return self.similarity < 0.9999


def lookup(
    conn: sqlite3.Connection,
    *,
    corpus_id: str,
    scope: str,
    question_vector: Vector,
    threshold: float = DEFAULT_THRESHOLD,
) -> CachedAnswer | None:
    """Best entry above `threshold` within this corpus and scope, or None.

    The SQL filter does the isolation; the similarity search only ranks what is already
    guaranteed to be reachable. Doing it the other way round — search then filter — is how
    a cross-corpus leak happens when someone forgets the second step.
    """
    rows = conn.execute(
        """
        SELECT id, question, answer_json, vector_json
        FROM qa_cache_meta
        WHERE corpus_id = ? AND part_id = ?
        """,
        (corpus_id, scope),
    ).fetchall()

    best: CachedAnswer | None = None
    for row in rows:
        similarity = cosine(question_vector, json.loads(row["vector_json"]))
        if similarity < threshold:
            continue
        if best is None or similarity > best.similarity:
            best = CachedAnswer(
                id=str(row["id"]),
                question=str(row["question"]),
                answer=json.loads(row["answer_json"]),
                similarity=similarity,
            )
    return best


def store(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    corpus_id: str,
    topic_id: str,
    scope: str,
    question: str,
    question_vector: Vector,
    answer: dict[str, object],
) -> str:
    entry_id = new_id("qa")
    conn.execute(
        """
        INSERT INTO qa_cache_meta
            (id, owner_id, corpus_id, topic_id, part_id, question, answer_json,
             vector_id, vector_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            owner_id,
            corpus_id,
            topic_id,
            scope,
            question,
            json.dumps(answer),
            entry_id,
            json.dumps(list(question_vector)),
        ),
    )
    conn.commit()
    return entry_id
