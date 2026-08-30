"""Cache threshold calibration (2B.9, G-03).

**Hit rate alone is not a result.** It is trivially maximised by lowering the threshold to
zero, at which point every question returns some cached answer and the cache is a random
answer generator with citations. So the threshold is calibrated against two numbers:

* the **hit rate** over a paraphrase set — questions that mean the same thing and *should*
  hit;
* the **false-hit count** over a near-miss set — questions that are lexically close but
  semantically different, and *must not* hit.

A false hit is not a cheaper answer. It is a wrong answer, delivered fluently, cited, and
about the right part — which is the hardest kind for a student to catch. That is why the
amendment says correctness is the binding constraint, and why this module reports the
false-hit count first.

Run it against a real embedding provider to calibrate; it takes any `embed` callable, so a
deterministic stub can drive it in replay with no key and no spend.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .cache import DEFAULT_THRESHOLD, lookup, store

Embedder = Callable[[str], Sequence[float]]


@dataclass(frozen=True)
class QuestionPair:
    """A seeded question and a probe, with what the probe *should* do."""

    seeded: str
    probe: str
    should_hit: bool
    note: str = ""


@dataclass
class ThresholdResult:
    threshold: float
    hits: int = 0
    misses: int = 0
    false_hits: int = 0
    true_rejections: int = 0
    similarities: list[float] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return 0.0 if total == 0 else self.hits / total

    @property
    def acceptable(self) -> bool:
        """A threshold is only acceptable if it makes NO false hits.

        Deliberately absolute rather than a rate. One wrong answer served confidently is
        the failure this whole design exists to avoid, and there is no hit rate that buys
        it back.
        """
        return self.false_hits == 0


def evaluate(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    corpus_id: str,
    topic_id: str,
    scope: str,
    embed: Embedder,
    paraphrases: Sequence[QuestionPair],
    near_misses: Sequence[QuestionPair],
    thresholds: Sequence[float] = (0.80, 0.85, 0.90, DEFAULT_THRESHOLD, 0.95, 0.98),
) -> list[ThresholdResult]:
    """Seed the cache once, then probe it at each candidate threshold."""
    seeded: set[str] = set()
    for pair in [*paraphrases, *near_misses]:
        if pair.seeded in seeded:
            continue
        store(
            conn,
            owner_id=owner_id,
            corpus_id=corpus_id,
            topic_id=topic_id,
            scope=scope,
            question=pair.seeded,
            question_vector=embed(pair.seeded),
            answer={"text": f"cached answer for: {pair.seeded}"},
        )
        seeded.add(pair.seeded)

    results: list[ThresholdResult] = []
    for threshold in thresholds:
        result = ThresholdResult(threshold=threshold)
        for pair in [*paraphrases, *near_misses]:
            hit = lookup(
                conn,
                corpus_id=corpus_id,
                scope=scope,
                question_vector=embed(pair.probe),
                threshold=threshold,
            )
            if hit is not None:
                result.similarities.append(hit.similarity)
            if pair.should_hit:
                if hit is not None:
                    result.hits += 1
                else:
                    result.misses += 1
            elif hit is not None:
                result.false_hits += 1
            else:
                result.true_rejections += 1
        results.append(result)
    return results


def format_table(results: Sequence[ThresholdResult]) -> str:
    """The two-column table G-03 asks for. False hits first, because they are binding."""
    lines = [
        f"{'threshold':>9}  {'false hits':>10}  {'hit rate':>9}  {'hits':>5}  "
        f"{'misses':>6}  {'rejected':>8}  verdict",
        "-" * 72,
    ]
    for result in results:
        verdict = "usable" if result.acceptable else "UNSAFE - answers questions not asked"
        lines.append(
            f"{result.threshold:>9.2f}  {result.false_hits:>10}  {result.hit_rate:>8.0%}  "
            f"{result.hits:>5}  {result.misses:>6}  {result.true_rejections:>8}  {verdict}"
        )
    return "\n".join(lines)


def recommend(results: Sequence[ThresholdResult]) -> ThresholdResult | None:
    """The lowest threshold that makes no false hits — best hit rate among the safe ones.

    Lowest-safe rather than highest-safe: among thresholds that are all correct, the one
    that caches most is the cheapest, and correctness has already been established as the
    constraint rather than the objective.
    """
    safe = [r for r in results if r.acceptable]
    return min(safe, key=lambda r: r.threshold) if safe else None
