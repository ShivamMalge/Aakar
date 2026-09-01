"""Compare selection methods on the same golden set, same counts (2D.1f).

Two tables per method, because a selection rule decides two things and only reporting one
of them hides half the trade:

**Table 1 — selection.** False coverage, missed coverage, correct refusals. False coverage
is binding and absolute, as everywhere else: an uncovered question that gets answered
reaches a student as a fluent, cited, wrong answer about their own textbook.

**Table 2 — the same three faithfulness counts**, obtained by running the answer fixtures
through each method's pool instead of through the passage list the fixture names. This is
what couples the two halves. A marker in a fixture means *"the chunk the answer meant to
cite"*; if a method drops that chunk from the pool, the marker resolves to nothing and
count 1 moves. If a method keeps a wide pool of weak chunks, there is more for a claim to
be wrongly attributed to and count 2 moves. Neither shows up in the selection table.

No preference is computed anywhere in this module. It reports; the architect rules.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from aakar.rag.answer import build_prompt
from aakar.rag.index import Hit
from aakar.rag.retrieval import part_scope_terms

from .embedders import NamedEmbedder, embedder_from_env
from .faithfulness import MARKER, FaithfulnessReport, evaluate_answer
from .golden import AnswerFixture, GoldenSet, load_answers, load_golden_set, rank
from .selection import METHODS, Selection, SelectionMethod

#: Higher than production's 8: `margin_distribution` needs a distribution, and cutting the
#: corpus at 8 would measure the spread of the winners rather than of the chapter. The
#: golden chapter has 10 chunks, so this fetches all of them — which is exactly the gap
#: between this harness and production that `selection.margin_distribution` documents.
RETRIEVE_LIMIT = 10


@dataclass
class SelectionCounts:
    method: str
    covered: int = 0
    missed: int = 0
    false_coverage: int = 0
    refused: int = 0
    pool_sizes: list[int] = field(default_factory=list)
    false_ids: list[str] = field(default_factory=list)
    missed_ids: list[str] = field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        """Zero false coverage. Absolute, not a rate — the same rule as everywhere else."""
        return self.false_coverage == 0

    @property
    def coverage_rate(self) -> float:
        total = self.covered + self.missed
        return 0.0 if total == 0 else self.covered / total

    @property
    def mean_pool(self) -> float:
        """Reported beside every count: pool size is the confound in this comparison, and
        a method that looks faithful because it shows the model almost nothing is not
        better, it is quieter."""
        return sum(self.pool_sizes) / len(self.pool_sizes) if self.pool_sizes else 0.0


@dataclass(frozen=True)
class MethodComparison:
    method: SelectionMethod
    selection: SelectionCounts
    faithfulness: FaithfulnessReport
    embedder: NamedEmbedder

    @property
    def provisional(self) -> bool:
        return not self.method.certified or not self.embedder.calibrating


def _scored(
    golden: GoldenSet, embedder: NamedEmbedder
) -> tuple[dict[str, list[Hit]], dict[str, list[Hit]]]:
    """Rank the chapter once per question and once per fixture question.

    Ranked once and reused across methods on purpose: the comparison is between selection
    rules, and re-embedding per method would let embedding noise leak into the difference.
    """
    embed = embedder.build()
    vectors = [embed(chunk.text) for chunk in golden.chunks]

    by_question: dict[str, list[Hit]] = {}
    for question in golden.questions:
        terms = part_scope_terms(question.part, question.aliases)
        scoped = f"{' '.join(terms)} {question.question}"
        by_question[question.id] = rank(embed(scoped), golden.chunks, vectors)[:RETRIEVE_LIMIT]

    by_fixture: dict[str, list[Hit]] = {}
    lookup = {q.id: q for q in golden.questions}
    for fixture in load_answers():
        question = lookup[fixture.question_id]
        by_fixture[fixture.id] = by_question[question.id]
    return by_question, by_fixture


def renumber(text: str, intended: Sequence[str], pool: Sequence[Hit]) -> str:
    """Rewrite a fixture's markers from its own passage list into a method's pool.

    A fixture's ``[2]`` means "the second chunk this answer was written against" — a chunk
    id, not a position. Under a different pool that same chunk sits somewhere else, or
    nowhere. Rewriting to its new position keeps the answer's *intent* fixed while the
    selection changes underneath it, which is the only way the two are comparable.

    A chunk the method dropped is rewritten to a marker past the end of the pool: the model
    cited evidence that never reached it, which is precisely count 1 and precisely what a
    too-aggressive selection rule would cause in production.
    """
    positions = {hit.chunk_id: i for i, hit in enumerate(pool, start=1)}
    dropped = len(pool) + 1

    def rewrite(match: re.Match[str]) -> str:
        out: list[str] = []
        for raw in re.split(r"\s*,\s*", match.group(1)):
            index = int(raw)
            if 1 <= index <= len(intended):
                out.append(str(positions.get(intended[index - 1], dropped)))
            else:
                # A marker the fixture itself invented (a03's [9]) stays invented.
                out.append(str(dropped))
        return f"[{','.join(out)}]"

    return MARKER.sub(rewrite, text)


def compare(
    golden: GoldenSet | None = None,
    *,
    embedder: NamedEmbedder | None = None,
    methods: Sequence[str] = tuple(METHODS),
) -> list[MethodComparison]:
    """Run every method over the same rankings and report both tables for each."""
    golden = golden or load_golden_set()
    embedder = embedder or embedder_from_env()
    by_question, by_fixture = _scored(golden, embedder)
    fixtures = {f.id: f for f in load_answers()}

    out: list[MethodComparison] = []
    for name in methods:
        method = METHODS[name]
        counts = SelectionCounts(method=name)

        for question in golden.questions:
            chosen: Selection = method.select(by_question[question.id])
            counts.pool_sizes.append(chosen.pool_size)
            if question.answerable:
                if chosen.covered:
                    counts.covered += 1
                else:
                    counts.missed += 1
                    counts.missed_ids.append(question.id)
            elif chosen.covered:
                counts.false_coverage += 1
                counts.false_ids.append(question.id)
            else:
                counts.refused += 1

        report = FaithfulnessReport(
            provisional=golden.provisional or not embedder.calibrating,
            embedder=embedder.label,
        )
        for fixture in fixtures.values():
            report.merge(_grade_under(method, fixture, by_fixture[fixture.id], golden, embedder))

        out.append(
            MethodComparison(
                method=method, selection=counts, faithfulness=report, embedder=embedder
            )
        )
    return out


def _grade_under(
    method: SelectionMethod,
    fixture: AnswerFixture,
    ranked: Sequence[Hit],
    golden: GoldenSet,
    embedder: NamedEmbedder,
) -> FaithfulnessReport:
    chosen = method.select(ranked)
    pool = chosen.pool
    prompt = build_prompt("", pool)
    return evaluate_answer(
        renumber(fixture.text, fixture.passages, pool),
        prompt.numbering,
        provisional=golden.provisional or not embedder.calibrating,
        embedder=embedder.label,
    )


def format_comparison(results: Sequence[MethodComparison]) -> str:
    """Both tables, side by side, with no recommendation. The architect rules."""
    lines = [
        "selection method comparison (2D.1f)",
        "=" * 35,
        "PROVISIONAL - every method below is UNCERTIFIED and the embedder is lexical.",
        "No preference is computed here. The two tables measure different things and a",
        "method can win one while losing the other.",
        "",
        "1. selection - does the rule answer the right questions",
        f"{'method':>21}  {'false cover':>11}  {'coverage':>8}  {'missed':>6}  "
        f"{'refused':>7}  {'mean pool':>9}",
        "-" * 82,
    ]
    for result in results:
        counts = result.selection
        lines.append(
            f"{counts.method:>21}  {counts.false_coverage:>11}  {counts.coverage_rate:>7.0%}  "
            f"{counts.missed:>6}  {counts.refused:>7}  {counts.mean_pool:>9.1f}"
        )

    lines += [
        "",
        "2. citation faithfulness under that rule - same three counts as 2D.1c",
        f"{'method':>21}  {'1 unresolvable':>14}  {'2 unsupported':>13}  {'3 uncited':>9}  "
        f"{'(missing mk)':>12}  {'claims':>6}",
        "-" * 90,
    ]
    for result in results:
        report = result.faithfulness
        lines.append(
            f"{result.method.name:>21}  {report.unresolvable_markers:>14}  "
            f"{report.unsupported_sentences:>13}  {report.uncited_claims:>9}  "
            f"{report.missing_markers:>12}  {report.claims:>6}"
        )

    lines += ["", "  method notes:"]
    for result in results:
        lines.append(f"    {result.method.name}: {result.method.description}")
        lines.append(f"      certified: {result.method.certified} - {result.method.caveat}")
    return "\n".join(lines)
