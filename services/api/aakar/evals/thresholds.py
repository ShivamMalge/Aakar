"""Threshold calibration, parameterised by embedder (2D.1d).

Two thresholds in this system are pure functions of the embedder:

* the **cache similarity threshold** (D-041) — when two questions count as the same one;
* the **relevance floor** (2C.3) — when the chapter counts as not covering a question.

`aakar.rag.benchmark` already takes an `embed` callable, which is most of the job. What was
missing is the part that makes swapping embedders *configuration*: a name, so the result
carries which embedder produced it, and a refusal to present a number from a non-calibrating
embedder as final. Both live in `embedders.py`; this module is what consumes them.

## The floor sweep

The golden set is built for exactly this: six single-chunk and four multi-chunk questions
that **must** clear the floor, and five ``not_in_chapter`` questions that **must not**. The
five are deliberately hard — they name a part the chapter really discusses and ask something
it never says (the sclera's thickness in millimetres; what determines eye colour). A floor
tuned on easy negatives is a floor that has never refused anything, which is R2.

As with the cache threshold, **false coverage is the binding constraint**. A question the
chapter cannot answer that clears the floor produces a fluent, cited, wrong answer. A
question that should clear and does not produces "your chapter does not cover this" — which
is a worse experience and a true statement. Those are not symmetric, so the harness does not
optimise a single number across them: it reports the lowest floor that admits **zero** false
coverage, and shows what that costs in missed coverage.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from aakar.rag.benchmark import QuestionPair, ThresholdResult, evaluate, format_table, recommend
from aakar.rag.retrieval import DEFAULT_FLOOR, part_scope_terms

from .embedders import NamedEmbedder, embedder_from_env
from .golden import GOLDEN_DIR, GoldenSet, load_golden_set, rank

#: The sweep must span both failure modes or it measures nothing: low enough that the hard
#: negatives get through, high enough that real questions get refused. `DEFAULT_FLOOR` is
#: folded in rather than listed, so the shipped value is always one of the rows even after
#: 2D.2 moves it.
FLOORS: tuple[float, ...] = tuple(sorted({0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, DEFAULT_FLOOR}))

#: 0.05 steps across the interesting band (2D.1f). The coarse sweep jumps straight from
#: "admits two hard negatives" at 0.35 to "refuses two real questions" at 0.45, which is
#: the shape of a resolution problem as much as a separability one — a viable point could
#: sit between two rows and never appear. Reported beside the coarse table rather than
#: replacing it, so the earlier numbers stay checkable.
FINE_FLOORS: tuple[float, ...] = tuple(round(0.30 + 0.05 * i, 2) for i in range(7))

#: The band the *real* embedder's answer sits in. `gemini-embedding-001` scores a relevant
#: chunk far higher than the lexical stub does, so a sweep stopping at 0.60 shows a table in
#: which every row is UNSAFE and hides the number entirely. Reported alongside the 0.30-0.60
#: band rather than instead of it: the requested sweep stays checkable, and the answer is
#: visible.
WIDE_FLOORS: tuple[float, ...] = tuple(round(0.30 + 0.05 * i, 2) for i in range(13))


@dataclass(frozen=True)
class CalibrationResult:
    """A threshold table plus the two facts that decide whether it may be believed."""

    embedder: NamedEmbedder
    results: tuple[ThresholdResult, ...]
    provisional: bool
    #: Why it is provisional. Empty only when it is not.
    reason: str

    @property
    def recommended(self) -> ThresholdResult | None:
        return recommend(self.results)


def calibrate_cache_threshold(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    corpus_id: str,
    topic_id: str,
    scope: str,
    paraphrases: Sequence[QuestionPair],
    near_misses: Sequence[QuestionPair],
    embedder: NamedEmbedder | None = None,
    thresholds: Sequence[float] | None = None,
) -> CalibrationResult:
    """Run the D-041 sweep against a named embedder."""
    embedder = embedder or embedder_from_env()
    embed = embedder.build().query
    results = evaluate(
        conn,
        owner_id=owner_id,
        corpus_id=corpus_id,
        topic_id=topic_id,
        scope=scope,
        embed=embed,
        paraphrases=paraphrases,
        near_misses=near_misses,
        **({"thresholds": tuple(thresholds)} if thresholds is not None else {}),
    )
    return CalibrationResult(
        embedder=embedder,
        results=tuple(results),
        provisional=not embedder.calibrating,
        reason=embedder.caveat,
    )


# ------------------------------------------------------------------ the relevance floor


@dataclass
class FloorResult:
    floor: float
    #: Answerable questions that cleared the floor. Should be all of them.
    covered: int = 0
    #: Answerable questions the floor refused. Costly, but honest.
    missed: int = 0
    #: ``not_in_chapter`` questions that cleared the floor. Each one is a fabricated answer.
    false_coverage: int = 0
    #: ``not_in_chapter`` questions correctly refused.
    refused: int = 0
    false_ids: list[str] = field(default_factory=list)
    missed_ids: list[str] = field(default_factory=list)

    @property
    def coverage_rate(self) -> float:
        total = self.covered + self.missed
        return 0.0 if total == 0 else self.covered / total

    @property
    def acceptable(self) -> bool:
        """Absolute, not a rate — one confidently wrong answer is the failure this exists
        to prevent, and no coverage rate buys it back (same rule as the cache threshold)."""
        return self.false_coverage == 0


@dataclass(frozen=True)
class FloorCalibration:
    embedder: NamedEmbedder
    results: tuple[FloorResult, ...]
    provisional: bool
    reason: str
    golden_verified: bool

    @property
    def recommended(self) -> FloorResult | None:
        """Lowest floor admitting no false coverage: correct first, then most generous."""
        safe = [r for r in self.results if r.acceptable]
        return min(safe, key=lambda r: r.floor) if safe else None


def calibrate_relevance_floor(
    golden: GoldenSet | None = None,
    *,
    embedder: NamedEmbedder | None = None,
    floors: Sequence[float] = FLOORS,
    limit: int = 8,
) -> FloorCalibration:
    """Sweep the relevance floor over the golden set.

    Scores each question once and re-reads the same best-score at every candidate floor.
    Re-embedding per floor would be identical work with a chance of drifting, and the point
    is a sweep, not a benchmark of the embedder's throughput.
    """
    golden = golden or load_golden_set()
    embedder = embedder or embedder_from_env()
    embed = embedder.build()

    # Chunks are DOCUMENTS. Sending them through the query path is the asymmetry bug
    # `Embedders` exists to make impossible to write by accident.
    chunk_vectors = [embed.document(chunk.text) for chunk in golden.chunks]

    best_scores: dict[str, float] = {}
    for question in golden.questions:
        terms = part_scope_terms(question.part, question.aliases)
        # Identical to the production query construction in `retrieval.retrieve`: the
        # scope terms are what the click already told us, and a floor calibrated on the
        # bare question would be a floor for a query the system never sends.
        scoped = f"{' '.join(terms)} {question.question}"
        ranked = rank(embed.query(scoped), golden.chunks, chunk_vectors)[:limit]
        best_scores[question.id] = ranked[0].score if ranked else 0.0

    results: list[FloorResult] = []
    for floor in floors:
        result = FloorResult(floor=floor)
        for question in golden.questions:
            clears = best_scores[question.id] >= floor
            if question.answerable:
                if clears:
                    result.covered += 1
                else:
                    result.missed += 1
                    result.missed_ids.append(question.id)
            elif clears:
                result.false_coverage += 1
                result.false_ids.append(question.id)
            else:
                result.refused += 1
        results.append(result)

    return FloorCalibration(
        embedder=embedder,
        results=tuple(results),
        provisional=not embedder.calibrating or golden.provisional,
        reason=embedder.caveat
        or ("golden labels are not human-verified" if golden.provisional else ""),
        golden_verified=golden.verified,
    )


def format_floor_table(calibration: FloorCalibration) -> str:
    """False coverage first, because it is the binding constraint."""
    lines: list[str] = []
    if calibration.provisional:
        lines += [
            "PROVISIONAL - method closed, number open.",
            f"  embedder: {calibration.embedder.label}",
            f"  golden set human-verified: {calibration.golden_verified}",
            f"  {calibration.reason}",
            "",
        ]
    lines += [
        f"{'floor':>6}  {'false cover':>11}  {'coverage':>8}  {'covered':>7}  "
        f"{'missed':>6}  {'refused':>7}  verdict",
        "-" * 76,
    ]
    for result in calibration.results:
        verdict = "usable" if result.acceptable else "UNSAFE - answers uncovered questions"
        lines.append(
            f"{result.floor:>6.2f}  {result.false_coverage:>11}  {result.coverage_rate:>7.0%}  "
            f"{result.covered:>7}  {result.missed:>6}  {result.refused:>7}  {verdict}"
        )
    best = calibration.recommended
    if best is None:
        lines += ["", "  No floor in this sweep refuses every uncovered question."]
    else:
        lines += [
            "",
            f"  lowest safe floor: {best.floor:.2f} "
            f"(coverage {best.coverage_rate:.0%}, missed {best.missed_ids or 'none'})",
        ]
    return "\n".join(lines)


__all__ = [
    "CalibrationResult",
    "FloorCalibration",
    "FloorResult",
    "calibrate_cache_threshold",
    "calibrate_relevance_floor",
    "format_floor_table",
    "format_table",
]


def load_cache_pairs(
    directory: Path | None = None,
) -> tuple[list[QuestionPair], list[QuestionPair]]:
    """The committed paraphrase / near-miss set.

    Committed rather than living in a script: the 2C recalibration was run from an ad-hoc
    one, which is why the number could not simply be re-measured against a different
    embedder — the pairs had to be reconstructed first.
    """
    payload = json.loads(
        ((directory or GOLDEN_DIR) / "cache-pairs.json").read_text(encoding="utf-8")
    )
    return (
        [
            QuestionPair(p["seeded"], p["probe"], should_hit=True, note=p.get("note", ""))
            for p in payload["paraphrases"]
        ],
        [
            QuestionPair(p["seeded"], p["probe"], should_hit=False, note=p.get("note", ""))
            for p in payload["near_misses"]
        ],
    )


def sweep_cache_threshold(embedder: NamedEmbedder) -> CalibrationResult:
    """Run the D-041 sweep on a throwaway in-memory database.

    The cache is bookkeeping, not the artefact; persisting a calibration run into the real
    database would leave seeded answers that a later question could hit.
    """
    from aakar.auth import ensure_owner  # noqa: PLC0415 - avoids a cycle at import time
    from aakar.db import apply_schema, connect

    paraphrases, near_misses = load_cache_pairs()
    conn = connect(Path(":memory:"))
    apply_schema(conn)
    owner = ensure_owner(conn, "sweep@local", "sweep-only-password-long-enough")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('golden', 'gh', 'g')")
    conn.execute(
        "INSERT INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES ('t1', ?, 'golden', 'eye', 'Eye')",
        (owner,),
    )
    conn.commit()
    return calibrate_cache_threshold(
        conn,
        owner_id=owner,
        corpus_id="golden",
        topic_id="t1",
        scope="eye",
        paraphrases=paraphrases,
        near_misses=near_misses,
        embedder=embedder,
    )
