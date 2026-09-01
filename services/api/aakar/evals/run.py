"""Run the 2D.1 harnesses over the golden set. ``python -m aakar.evals.run``

Prints three things, in this order, because that is the order in which one invalidates the
next:

1. **What produced these numbers** — the embedder, and whether the golden labels are
   human-verified. Everything below is stamped PROVISIONAL until both are true.
2. **The relevance floor sweep** — retrieval quality, from `thresholds.py`.
3. **Citation faithfulness** — the three counts, from `faithfulness.py`.

Runs with no API key and no container. It measures the *harness*, not the product: the
answers it grades are hand-written fixtures, and the embedder behind the floor sweep is
lexical. The method is what is closed here. The numbers are open until 2D.2.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from aakar.rag.answer import build_prompt

from .embedders import NamedEmbedder, embedder_from_env
from .faithfulness import FaithfulnessReport, evaluate_answer, format_report
from .golden import GOLDEN_DIR, GoldenSet, load_golden_set
from .thresholds import calibrate_relevance_floor, format_floor_table


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


def grade(
    fixture: AnswerFixture, golden: GoldenSet, *, embedder: NamedEmbedder
) -> FaithfulnessReport:
    """Grade one fixture answer against the passages its own entry names.

    Goes through `build_prompt` rather than constructing the numbering here, so the eval
    and the prompt cannot disagree about what marker [1] means. If numbering ever changes —
    zero-based, say — every count moves with it instead of the eval quietly grading against
    a scheme the model was never given.
    """
    hits = [golden.by_id(chunk_id) for chunk_id in fixture.passages]
    prompt = build_prompt("", hits)
    return evaluate_answer(
        fixture.text,
        prompt.numbering,
        provisional=golden.provisional or not embedder.calibrating,
        embedder=embedder.label,
    )


def main(out: TextIO = sys.stdout) -> int:
    golden = load_golden_set()
    embedder = embedder_from_env()
    fixtures = load_answers()

    print("Aakar 2D.1 evaluation harness", file=out)
    print("=" * 29, file=out)
    print(f"  chapter        : {golden.source}", file=out)
    print(f"  chunks         : {len(golden.chunks)} ({len(golden.ocr_chunk_ids)} OCR)", file=out)
    print(f"  questions      : {len(golden.questions)}", file=out)
    print(f"  answer fixtures: {len(fixtures)} (hand-written, not model output)", file=out)
    print(f"  embedder       : {embedder.label}", file=out)
    print(f"  labels verified: {golden.verified}", file=out)
    for key, note in golden.scope_limits.items():
        if key[:1].isdigit():
            # Only the numbered limits. Printed on every run rather than left in the file,
            # because a caveat that has to be looked up is a caveat that will not be.
            print(f"  scope limit    : {note.split('.')[0]}.", file=out)
    if golden.provisional or not embedder.calibrating:
        print(file=out)
        print("  PROVISIONAL. Method closed, numbers open.", file=out)
        if golden.provisional:
            print("   - golden labels are PROPOSED and not human-verified", file=out)
        if not embedder.calibrating:
            print(f"   - {embedder.caveat}", file=out)
    print(file=out)

    print(format_floor_table(calibrate_relevance_floor(golden, embedder=embedder)), file=out)
    print(file=out)

    combined = FaithfulnessReport(provisional=golden.provisional, embedder=embedder.label)
    print("per-fixture verdicts", file=out)
    print("-" * 20, file=out)
    for fixture in fixtures:
        report = grade(fixture, golden, embedder=embedder)
        combined.merge(report)
        fired = _fired(report)
        ok = "ok " if fixture.expect in fired else "FAIL"
        print(
            f"  {ok} {fixture.id}  expected {fixture.expect:<22} fired {', '.join(fired)}",
            file=out,
        )
    print(file=out)
    print(format_report(combined, label="all fixtures"), file=out)
    return 0


def _fired(report: FaithfulnessReport) -> list[str]:
    """Which counts this answer moved. ``clean`` when it moved none."""
    fired = [
        name
        for name, value in (
            ("unresolvable_markers", report.unresolvable_markers),
            ("unsupported_sentences", report.unsupported_sentences),
            ("uncited_claims", report.uncited_claims),
            ("missing_markers", report.missing_markers),
            ("needs_human", report.needs_human),
        )
        if value
    ]
    return fired or ["clean"]


if __name__ == "__main__":
    raise SystemExit(main())
