"""2D.1f — selection methods, their certification guard, and the comparison harness.

Two things are under test and they are different: that each *method* behaves as described,
and that an uncertified one **cannot reach a student's answer**. The second is the one that
matters, because the first is only ever measured on a stub right now.
"""

from __future__ import annotations

import pytest

from aakar.evals.compare import compare, format_comparison, renumber
from aakar.evals.embedders import resolve_embedder
from aakar.evals.golden import load_answers, load_golden_set
from aakar.evals.selection import (
    METHODS,
    SHIPPED,
    SelectionMethod,
    UncertifiedMethod,
    absolute,
    margin_distribution,
    margin_top2,
    resolve_method,
    shipped_method,
)
from aakar.evals.thresholds import FINE_FLOORS, WIDE_FLOORS
from aakar.rag.index import Hit
from aakar.rag.retrieval import DEFAULT_FLOOR


def hit(chunk_id: str, score: float, text: str = "some chapter text") -> Hit:
    return Hit(
        chunk_id=chunk_id,
        corpus_id="c",
        document_id="d",
        text=text,
        page_index=0,
        page_label="1",
        section=None,
        source="digital",
        score=score,
    )


# ------------------------------------------------------ the certification guard


def test_no_method_ships_until_it_is_measured_on_a_real_embedder() -> None:
    """The constraint, stated as a test. Every method is uncertified today, so the shipped
    lookup refuses all of them — which is correct: the production path does not call it yet,
    and wiring one in is the ruling that follows 2D.2, not something that can happen first."""
    assert all(not m.certified for m in METHODS.values())
    with pytest.raises(UncertifiedMethod):
        shipped_method()


def test_an_uncertified_method_cannot_be_shipped_by_setting_an_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure this exists to prevent: a method that reads well in a comparison table
    becoming the mechanism behind real answers because someone exported a variable."""
    monkeypatch.setenv("AAKAR_SELECTION_METHOD", "margin_distribution")
    with pytest.raises(UncertifiedMethod, match="not certified"):
        shipped_method()


def test_evaluating_an_uncertified_method_is_allowed() -> None:
    """`resolve_method` deliberately does not check certification. A harness that could only
    run trusted methods could never produce the evidence that makes one trusted."""
    assert resolve_method("margin_top2").name == "margin_top2"
    assert resolve_method(SHIPPED).name == "absolute"


def test_a_certified_method_would_be_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the guard: a lookup that raised unconditionally would pass both tests above
    and would also be useless the day a method is certified."""
    certified = SelectionMethod(
        name="fake", description="", certified=True, caveat="", select=absolute
    )
    monkeypatch.setitem(METHODS, "fake", certified)
    monkeypatch.setenv("AAKAR_SELECTION_METHOD", "fake")
    assert shipped_method() is certified


def test_an_unknown_method_names_the_ones_that_exist() -> None:
    with pytest.raises(KeyError, match="margin_top2"):
        resolve_method("reranker")


# ------------------------------------------------------------------ the methods


def test_absolute_reproduces_production_including_its_unfiltered_pool() -> None:
    """The pool is every hit — a chunk scoring 0.02 travels to the model beside one scoring
    0.9. That is what `ask()` does today, and stating it is half the point of this table."""
    hits = [hit("a", 0.90), hit("b", 0.20), hit("c", 0.02)]
    chosen = absolute(hits, floor=DEFAULT_FLOOR)
    assert chosen.covered
    assert chosen.pool_size == 3
    assert absolute([hit("a", 0.10)], floor=DEFAULT_FLOOR).covered is False


def test_margin_top2_refuses_when_nothing_stands_out() -> None:
    """Two chunks scoring the same means the corpus does not distinguish an answer, however
    high both scores are. An absolute floor cannot express that at all."""
    tie = margin_top2([hit("a", 0.80), hit("b", 0.79)], delta=0.10)
    assert not tie.covered
    clear = margin_top2([hit("a", 0.80), hit("b", 0.30)], delta=0.10)
    assert clear.covered
    # Scale-free: the same margin decides the same way at half the magnitude, which is the
    # property an absolute floor lacks and the reason this method is worth measuring.
    assert margin_top2([hit("a", 0.40), hit("b", 0.10)], delta=0.10).covered


def test_margin_top2_keeps_a_genuine_tie_in_the_pool() -> None:
    """Refusing to answer and refusing to cite are different. A tie is ambiguous evidence,
    not absent evidence, so both chunks stay available rather than one being picked."""
    tie = margin_top2([hit("a", 0.80), hit("b", 0.79), hit("c", 0.10)], delta=0.10)
    assert tie.pool_size == 2


def test_margin_distribution_measures_standing_out_from_the_corpus() -> None:
    outlier = margin_distribution([hit("a", 0.9), hit("b", 0.1), hit("c", 0.1), hit("d", 0.1)])
    assert outlier.covered
    flat = margin_distribution([hit("a", 0.6), hit("b", 0.6), hit("c", 0.6)])
    assert not flat.covered, "every chunk equally relevant means none is distinctly so"


def test_margin_distribution_never_hands_back_an_empty_pool() -> None:
    """A refusal is expressed by `covered`. An empty pool alongside `covered=True` would
    make "nothing to cite" and "nothing worth answering" indistinguishable downstream."""
    chosen = margin_distribution([hit("a", 0.31), hit("b", 0.30), hit("c", 0.29)])
    assert chosen.pool_size >= 1


def test_every_method_handles_an_empty_index() -> None:
    for method in METHODS.values():
        chosen = method.select([])
        assert not chosen.covered and chosen.pool_size == 0


# ------------------------------------------------------------------- renumbering


def test_renumber_follows_the_chunk_not_the_position() -> None:
    """A fixture's ``[2]`` names a chunk, not a slot. Under a different pool that chunk sits
    somewhere else, and rewriting to its new position is what keeps the answer's intent
    fixed while the selection changes underneath it."""
    pool = [hit("c03", 0.9), hit("c07", 0.5)]
    assert renumber("Blood supply [2].", ["c07", "c03"], pool) == "Blood supply [1]."


def test_a_dropped_chunk_becomes_an_unresolvable_marker() -> None:
    """The real consequence of an over-aggressive rule: the model cited evidence that never
    reached it. Count 1, arriving from selection rather than from the model."""
    pool = [hit("c03", 0.9)]
    assert renumber("Rhodopsin [1].", ["c09"], pool) == "Rhodopsin [2]."


def test_an_invented_marker_stays_invented() -> None:
    """a03 cites passage [9] against a one-passage list. Renumbering must not launder that
    into a valid marker, or the fixture would stop testing what it was written for."""
    pool = [hit("c08", 0.9)]
    assert renumber("Acuity [9].", ["c08"], pool) == "Acuity [2]."


def test_renumber_handles_a_multi_marker() -> None:
    pool = [hit("c01", 0.9), hit("c05", 0.4), hit("c03", 0.3)]
    assert renumber("Three layers [1,2].", ["c01", "c03"], pool) == "Three layers [1,3]."


# ------------------------------------------------------------------ the comparison


def test_the_comparison_reports_every_method_and_prefers_none() -> None:
    """The architect rules on the comparison. Nothing here computes a winner, and there is
    deliberately no `recommended` on the result — unlike the floor sweep, where the rule for
    picking is settled."""
    results = compare(embedder=resolve_embedder("local"))
    assert {r.method.name for r in results} == set(METHODS)
    assert all(r.provisional for r in results)
    assert not any(hasattr(r, "recommended") or hasattr(r, "best") for r in results)


def test_the_comparison_reports_both_tables_because_a_method_can_split_them() -> None:
    """The reason two tables exist: Table 1 does not determine Table 2.

    `margin_distribution` answers the MOST questions here and is the worst on all three
    faithfulness counts. More coverage is not better retrieval — it answers more by cutting
    the pool to about one chunk, which the selection table alone would show as a win.
    """
    results = {r.method.name: r for r in compare(embedder=resolve_embedder("local"))}
    widest = results["margin_distribution"]
    careful = results["margin_top2"]

    assert widest.selection.coverage_rate > careful.selection.coverage_rate
    assert widest.selection.false_coverage > careful.selection.false_coverage
    for counts in ("unresolvable_markers", "unsupported_sentences", "uncited_claims"):
        assert getattr(widest.faithfulness, counts) >= getattr(careful.faithfulness, counts)
    assert widest.faithfulness.unresolvable_markers > careful.faithfulness.unresolvable_markers, (
        "the tables would be redundant if they always agreed"
    )


def test_pool_size_is_reported_beside_the_counts() -> None:
    """The confound, surfaced rather than hidden: a method can look faithful by showing the
    model almost nothing, which is not better, only quieter."""
    results = {r.method.name: r for r in compare(embedder=resolve_embedder("local"))}
    assert results["absolute"].selection.mean_pool > results["margin_top2"].selection.mean_pool
    assert "mean pool" in format_comparison(list(results.values()))


def test_the_comparison_runs_every_fixture_through_every_method() -> None:
    golden = load_golden_set()
    fixtures = load_answers()
    for result in compare(golden, embedder=resolve_embedder("local")):
        assert len(result.selection.pool_sizes) == len(golden.questions)
        assert result.faithfulness.claims > 0, "no fixture reached the harness"
    assert len(fixtures) == 8


def test_the_printed_comparison_refuses_to_recommend() -> None:
    printed = format_comparison(compare(embedder=resolve_embedder("local")))
    assert "PROVISIONAL" in printed and "UNCERTIFIED" in printed
    assert "recommend" not in printed.lower()


# ------------------------------------------------------------------ the fine sweep


def test_the_fine_sweep_covers_the_band_at_0_05_steps() -> None:
    """The architect's requested band, kept exactly. It contains no safe row on the real
    embedder — the finding — so the shipped value lives in the wider sweep instead."""
    assert FINE_FLOORS == (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
    assert DEFAULT_FLOOR not in FINE_FLOORS
    assert DEFAULT_FLOOR in WIDE_FLOORS, "the shipped value must be one of the swept rows"
