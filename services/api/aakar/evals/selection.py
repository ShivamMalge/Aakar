"""Coverage-selection methods, registered and certified (2D.1f).

The 2D.1 sweep showed no absolute cosine floor separating covered from uncovered on the
local embedder: 0.35 admitted two hard negatives, 0.45 refused two real questions. An
absolute floor is also **corpus-dependent** — the five-sentence `test_retrieval` fixture
admits nothing at 0.45 while the ten-chunk golden chapter is fine at the same value — which
means the number is partly a property of how much text happens to be indexed.

A margin rule asks a different question. Not *"is this score high?"* but *"does one chunk
stand out from the others?"*, which is scale-free in a way a raw cosine is not.

## Certification, the same shape as `embedders.py`

Each method carries `certified`: whether it has been measured against a **real** embedder.
`shipped_method()` refuses an uncertified one, so a method can be evaluated freely and
still cannot become the mechanism a student's answer runs through by someone setting an
environment variable. Everything here is `certified=False` until 2D.2.

## A method decides two things, and both are reported

`covered` — does the chapter answer this at all (Rule 6) — and `pool`, which chunks are
worth putting in front of the model. They are not separable: a rule confident enough to
answer is making a claim about which evidence is good.

`absolute` reproduces **production exactly**, and that is itself worth seeing: its pool is
*every* retrieved hit, including ones scoring far below the floor that just refused an
entire question. The model is handed chunks the selection rule already judged irrelevant.
The margin methods cut their pool at their own boundary, so pool size is reported beside
every count rather than left as a hidden confound in the comparison.
"""

from __future__ import annotations

import os
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from aakar.rag.index import Hit
from aakar.rag.retrieval import DEFAULT_FLOOR

ENV_VAR = "AAKAR_SELECTION_METHOD"

#: The mechanism `retrieval.py` ships today. Changing it is an architect ruling, not a
#: config change — see `shipped_method`.
SHIPPED = "absolute"


@dataclass(frozen=True)
class Selection:
    """One method's verdict on one question."""

    covered: bool
    #: The chunks this method would put in the prompt, best first.
    pool: tuple[Hit, ...]
    #: The rule's own statistic, for reading a table rather than guessing at one.
    statistic: float

    @property
    def pool_size(self) -> int:
        return len(self.pool)


SelectFn = Callable[[Sequence[Hit]], Selection]


@dataclass(frozen=True)
class SelectionMethod:
    name: str
    description: str
    #: False until measured against a real embedder. Blocks it from shipping (2D.1f).
    certified: bool
    caveat: str
    select: SelectFn


def _empty(statistic: float = 0.0) -> Selection:
    return Selection(covered=False, pool=(), statistic=statistic)


def absolute(hits: Sequence[Hit], *, floor: float = DEFAULT_FLOOR) -> Selection:
    """Production, unchanged: top-1 against a fixed cosine floor.

    The pool is **every** hit, which is what `ask()` passes to the prompt today. A chunk
    scoring 0.05 travels to the model alongside one scoring 0.6, so the floor gates whether
    to answer and does nothing about what the answer is built from.
    """
    if not hits:
        return _empty()
    top = hits[0].score
    return Selection(covered=top >= floor, pool=tuple(hits), statistic=top)


def margin_top2(hits: Sequence[Hit], *, delta: float = 0.10) -> Selection:
    """Top-1 relative to top-2: answer when one chunk stands clear of the next.

    Scale-free where an absolute floor is not — it asks whether the corpus distinguishes an
    answer, not whether cosine happened to land above a number. The pool is everything
    within `delta` of the top, so a genuine tie keeps both chunks rather than picking one
    arbitrarily.

    **Its blind spot, stated:** a chapter that says the same thing twice produces two
    near-identical top scores and reads as "no clear answer" — the failure mode is exactly
    inverted from the absolute floor's, which is why they need measuring against each other
    rather than reasoning about.
    """
    if not hits:
        return _empty()
    top = hits[0].score
    if len(hits) == 1:
        # Nothing to stand out from. Treated as covered on the top score alone: a
        # single-chunk corpus is not evidence of ambiguity.
        return Selection(covered=top > 0.0, pool=tuple(hits), statistic=top)
    margin = top - hits[1].score
    pool = tuple(h for h in hits if h.score >= top - delta)
    return Selection(covered=margin >= delta, pool=pool, statistic=margin)


def margin_distribution(hits: Sequence[Hit], *, z: float = 1.5) -> Selection:
    """Top-1 relative to the score distribution: how many standard deviations it stands out.

    Answers "is this chunk unusual *for this corpus*", which is the question an absolute
    floor keeps failing to ask. Robust to a corpus whose scores all sit high or all sit low.

    **The deployment cost, because it is not free:** this needs scores for enough of the
    corpus to have a distribution, while production fetches `limit=8`. Computing it over the
    top 8 measures the spread of the *winners*, not of the corpus, and will read differently
    from what this harness measures over all ten golden chunks. That gap is a real
    difference between the harness and production, and it must be closed before this method
    could ship, not after.
    """
    if not hits:
        return _empty()
    scores = [h.score for h in hits]
    top = scores[0]
    if len(scores) < 3:  # noqa: PLR2004 - stdev of two points is not a distribution
        return Selection(covered=top > 0.0, pool=tuple(hits), statistic=top)
    spread = statistics.pstdev(scores)
    if spread == 0.0:
        # Every chunk equally relevant means none is distinctly so.
        return _empty()
    mean = statistics.fmean(scores)
    score_z = (top - mean) / spread
    pool = tuple(h for h in hits if (h.score - mean) / spread >= z)
    # Never an empty pool while the corpus has anything: a refusal is expressed by
    # `covered`, and handing back nothing to cite would make the two indistinguishable.
    return Selection(covered=score_z >= z, pool=pool or tuple(hits[:1]), statistic=score_z)


#: A method's caveat is about the METHOD. Which embedder produced a given table is the
#: embedder's business and is printed from `NamedEmbedder.caveat` — an earlier version
#: hardcoded "comes from the local lexical stub" here, which then printed a falsehood the
#: moment the same table was produced on the real embedder.
UNCERTIFIED = "no architect ruling has certified this method for the shipped path (2D.1f)."

METHODS: dict[str, SelectionMethod] = {
    "absolute": SelectionMethod(
        name="absolute",
        description=f"top-1 >= {DEFAULT_FLOOR} (production)",
        certified=False,
        caveat=UNCERTIFIED + " Its floor is DEFAULT_FLOOR, itself interim and uncertified (D-050).",
        select=absolute,
    ),
    "margin_top2": SelectionMethod(
        name="margin_top2",
        description="top-1 minus top-2 >= 0.10",
        certified=False,
        caveat=UNCERTIFIED,
        select=margin_top2,
    ),
    "margin_distribution": SelectionMethod(
        name="margin_distribution",
        description="top-1 at least 1.5 sd above the corpus mean",
        certified=False,
        caveat=UNCERTIFIED
        + " Measured here over the whole corpus while production fetches only the top 8 — "
        "see the docstring; that gap is unclosed.",
        select=margin_distribution,
    ),
}


class UncertifiedMethod(RuntimeError):
    """A selection method that has not been measured against a real embedder cannot ship."""


def resolve_method(name: str) -> SelectionMethod:
    """Look one up for **evaluation**. Certification is not checked here on purpose: the
    whole point of the harness is to run methods that are not yet trusted."""
    try:
        return METHODS[name]
    except KeyError:
        known = ", ".join(sorted(METHODS))
        raise KeyError(f"unknown selection method {name!r}; known: {known}") from None


def shipped_method() -> SelectionMethod:
    """The method a real answer runs through. Refuses an uncertified one.

    This is the guard the architect asked for: a method may be evaluated by anyone, and
    cannot become the shipped mechanism by someone exporting an environment variable. While
    every method is uncertified this raises for all of them, which is correct — the
    production path does not call it yet, and wiring it in is the ruling that follows 2D.2's
    measurement rather than something that can happen by accident before it.
    """
    name = os.environ.get(ENV_VAR, SHIPPED)
    method = resolve_method(name)
    if not method.certified:
        raise UncertifiedMethod(
            f"selection method {name!r} is not certified against a real embedder "
            f"({method.caveat}). Measure it in 2D.2 and record the ruling before shipping "
            "it; an uncertified method must not reach a student's answer by configuration."
        )
    return method
