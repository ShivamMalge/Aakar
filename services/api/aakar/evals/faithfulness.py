"""Citation faithfulness (2D.1c) — the eval that makes the product's claim testable.

**Three counts, never a score.** A single number averages away the difference between
"cited a passage that does not exist" and "made a claim from nowhere", and those need
different fixes: the first is a prompt problem, the second is a grounding problem.

The failure this catches is specific and nasty: **an answer that is fluent, correct, and
cites the wrong chunk.** Nothing about it looks wrong. The prose is right, the marker is a
real number, the page renders. Only someone who opens the cited chunk and reads it finds
out — which is exactly what nobody does at scale, and exactly what this automates.

## The three counts

1. ``unresolvable_markers`` — a marker naming a passage that was never retrieved. Pure
   invention; the cheapest to detect and the easiest to fix.
2. ``unsupported_sentences`` — the marker resolves, but the cited chunk does not state the
   claim. **This is the one that matters.** It is the fluent-and-wrong case.
3. ``uncited_claims`` — a factual claim carrying no marker whose content appears in no
   retrieved chunk. Fabrication, not merely sloppy citation.

``missing_markers`` is reported alongside them and is deliberately *not* part of count 3: a
true claim that sits in a retrieved chunk but carries no marker is a formatting failure, not
a fabrication, and merging the two would let a prompt fix look like a grounding fix.

## Judging support without a judge model

`supports()` is lexical by design. It asks whether the sentence's content words appear in
the cited chunk. That over-reports support for a paraphrase; it under-reports nothing, since
a sentence sharing no content words with its citation is not supported by it under any
reading. So a non-zero count 2 is a real finding, and a zero one is a floor, not a proof.

An LLM judge would be more sensitive and would also be the thing under test judging itself,
which is how an eval becomes a mirror. Where the lexical check is genuinely ambiguous the
harness says so: ``needs_human`` is a fourth number, not folded into pass or fail.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from aakar.rag.index import Hit

#: Words carrying no topical signal. Kept short on purpose: an aggressive stop list makes
#: short sentences look unsupported by deleting everything they contain.
STOPWORDS = frozenset(
    {
        "about",
        "also",
        "and",
        "are",
        "but",
        "can",
        "did",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "into",
        "its",
        "not",
        "onto",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "too",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "will",
        "with",
        "you",
        "your",
    }
)

MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: A sentence sharing at least this fraction of its content words with the cited chunk
#: counts as supported; below ``UNCERTAIN`` it counts as unsupported. Between the two the
#: harness refuses to decide rather than guessing in whichever direction flatters it.
SUPPORTED_AT = 0.6
UNCERTAIN = 0.3

#: A fragment with fewer content words than this carries no checkable claim ("It does.").
MIN_CLAIM_WORDS = 3

#: supported | unsupported | uncertain | uncited | missing_marker | not_a_claim
Verdict = str


def content_words(text: str) -> set[str]:
    """Lowercase alphabetic words of three or more characters, minus stopwords."""
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def supports(sentence: str, chunk_text: str) -> float:
    """Fraction of the sentence's content words that appear in the chunk.

    A lower bound on support — see the module docstring on why an LLM judge is the wrong
    instrument for an eval of the model being judged.
    """
    words = content_words(sentence)
    if not words:
        return 1.0
    return len(words & content_words(chunk_text)) / len(words)


#: Phrases that mark the Rule 6 refusal. A refusal is not a claim, and scoring it as an
#: uncited one would punish the single behaviour this whole design exists to produce.
#:
#: This is a keyword list and will miss an unusually phrased refusal. That failure runs in
#: the safe direction: a missed refusal is reported as an uncited claim, so the harness
#: over-reports a problem rather than hiding one. The reverse — inferring "this sentence is
#: only talking about the passages" from structure — would let a fabrication phrased as a
#: hedge disappear from count 3, which is the failure that must never be silent.
REFUSALS = (
    "does not appear to cover",
    "does not cover",
    "do not cover",
    "is not covered",
    "are not covered",
    "not covered in",
    "nothing in your chapter",
    "nothing in the passages",
    "the passages do not",
    "passages provided do not",
    "not stated in",
    "no information about",
    "cannot answer",
    "does not say",
    "do not say",
    "says nothing about",
    "say nothing about",
    "does not mention",
    "do not mention",
    "nothing in the uploaded material",
)


def is_refusal(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(phrase in lowered for phrase in REFUSALS)


@dataclass(frozen=True)
class SentenceVerdict:
    sentence: str
    markers: tuple[int, ...]
    #: Markers naming a passage that was never in the prompt.
    unresolvable: tuple[int, ...]
    #: Best overlap achieved against any chunk this sentence cites.
    overlap: float
    #: Best overlap against ANY retrieved chunk, cited or not. Separates "wrong citation"
    #: from "not in the corpus at all", which is the whole point of counts 2 and 3.
    best_in_pool: float
    pool_match: str | None
    verdict: Verdict

    @property
    def is_claim(self) -> bool:
        return self.verdict != "not_a_claim"


@dataclass
class FaithfulnessReport:
    """Four numbers and the sentences behind them. Never a score."""

    sentences: list[SentenceVerdict] = field(default_factory=list)
    #: Set when the golden labels driving this run were not human-verified (D-041).
    provisional: bool = False
    #: What produced the retrieval this answer was graded against.
    embedder: str = "unknown"

    @property
    def unresolvable_markers(self) -> int:
        """Count 1: markers pointing at passages that were never retrieved."""
        return sum(len(s.unresolvable) for s in self.sentences)

    @property
    def unsupported_sentences(self) -> int:
        """Count 2: the marker resolves, but the cited chunk does not state the claim."""
        return sum(1 for s in self.sentences if s.verdict == "unsupported")

    @property
    def uncited_claims(self) -> int:
        """Count 3: an uncited claim that is in no retrieved chunk. Fabrication."""
        return sum(1 for s in self.sentences if s.verdict == "uncited")

    @property
    def missing_markers(self) -> int:
        """Reported beside count 3, never inside it: true but uncited is a different bug."""
        return sum(1 for s in self.sentences if s.verdict == "missing_marker")

    @property
    def needs_human(self) -> int:
        """Lexically ambiguous. Not folded into pass or fail — that would be a guess."""
        return sum(1 for s in self.sentences if s.verdict == "uncertain")

    @property
    def supported(self) -> int:
        return sum(1 for s in self.sentences if s.verdict == "supported")

    @property
    def claims(self) -> int:
        return sum(1 for s in self.sentences if s.is_claim)

    @property
    def clean(self) -> bool:
        """All three counts zero. ``needs_human`` does not disqualify — it escalates."""
        return (
            self.unresolvable_markers == 0
            and self.unsupported_sentences == 0
            and self.uncited_claims == 0
        )

    def failures(self) -> list[SentenceVerdict]:
        """The sentences behind the counts. A count with no example is not actionable."""
        return [
            s
            for s in self.sentences
            if s.verdict in {"unsupported", "uncited", "missing_marker"} or s.unresolvable
        ]

    def merge(self, other: FaithfulnessReport) -> None:
        """Fold another answer's verdicts in. Provisional is sticky: one unverified input
        makes the whole aggregate unverified, and the reverse would launder it."""
        self.sentences.extend(other.sentences)
        self.provisional = self.provisional or other.provisional


def _best_in_pool(prose: str, pool: Sequence[Hit]) -> tuple[float, str | None]:
    """Best support for this sentence anywhere in what retrieval returned."""
    best, which = 0.0, None
    for hit in pool:
        score = supports(prose, hit.text)
        if score > best:
            best, which = score, hit.chunk_id
    return round(best, 3), which


def evaluate_answer(
    answer: str,
    numbering: Mapping[int, Hit],
    *,
    retrieved: Sequence[Hit] | None = None,
    provisional: bool = False,
    embedder: str = "unknown",
) -> FaithfulnessReport:
    """Grade one answer against the passages it was actually given.

    ``numbering`` is the marker map from `aakar.rag.answer.build_prompt` — the ground truth
    for what the model could legitimately cite. ``retrieved`` defaults to those same chunks
    and exists so a caller can ask *"is this claim anywhere in what we retrieved"*
    separately from *"is it in the chunk it cited"*. Those are counts 3 and 2, and keeping
    them apart is the only reason the report is actionable.
    """
    pool = list(retrieved if retrieved is not None else numbering.values())
    report = FaithfulnessReport(provisional=provisional, embedder=embedder)

    for raw in SENTENCE.split(answer.strip()):
        sentence = raw.strip()
        if not sentence:
            continue

        markers: list[int] = []
        for group in MARKER.findall(sentence):
            markers.extend(int(n) for n in re.split(r"\s*,\s*", group))
        # Removing "[1]" leaves "... light ." — cosmetic for the word overlap, but the
        # report prints these sentences back to a human, and a stray space before a full
        # stop makes a real finding look like a formatting bug.
        prose = re.sub(r"\s+([.,;:!?])", r"\g<1>", MARKER.sub("", sentence)).strip()
        prose = re.sub(r"\s{2,}", " ", prose)

        best_in_pool, pool_match = _best_in_pool(prose, pool)

        if is_refusal(prose) or len(content_words(prose)) < MIN_CLAIM_WORDS:
            report.sentences.append(
                SentenceVerdict(
                    prose, tuple(markers), (), 1.0, best_in_pool, pool_match, "not_a_claim"
                )
            )
            continue

        unresolvable = tuple(n for n in markers if n not in numbering)
        resolvable = [numbering[n] for n in markers if n in numbering]

        if not markers:
            # Rule 1 broken. Which count it lands in depends on whether the claim is in the
            # corpus at all: uncited-and-absent is fabrication (count 3); uncited-but-present
            # is a missing marker. The student can check neither, but the fixes differ.
            verdict = "missing_marker" if best_in_pool >= SUPPORTED_AT else "uncited"
            report.sentences.append(
                SentenceVerdict(prose, (), (), 0.0, best_in_pool, pool_match, verdict)
            )
            continue

        overlap = max((supports(prose, hit.text) for hit in resolvable), default=0.0)

        if not resolvable:
            # Every marker was invented. Counted once here and once per bad marker in
            # count 1 — they measure different things: sentences wrong vs markers wrong.
            verdict = "unsupported"
        elif overlap >= SUPPORTED_AT:
            verdict = "supported"
        elif overlap < UNCERTAIN:
            verdict = "unsupported"
        else:
            verdict = "uncertain"

        report.sentences.append(
            SentenceVerdict(
                prose,
                tuple(markers),
                unresolvable,
                round(overlap, 3),
                best_in_pool,
                pool_match,
                verdict,
            )
        )

    return report


def format_report(report: FaithfulnessReport, *, label: str = "", examples: int = 5) -> str:
    """Counts, printed as counts. Never summed, never averaged into a score."""
    head = f"citation faithfulness{f' - {label}' if label else ''}"
    lines = [head, "=" * len(head)]
    if report.provisional:
        lines += [
            "PROVISIONAL - method closed, number open.",
            f"  embedder: {report.embedder}",
            "  Golden labels are not human-verified and/or this is not the embedder that",
            "  ships. These counts prove the harness runs; they do not measure the product.",
            "",
        ]
    lines += [
        f"  claims made                            : {report.claims}",
        f"  supported                              : {report.supported}",
        "",
        f"  1. markers naming no retrieved passage : {report.unresolvable_markers}",
        "  2. sentences the cited chunk does not",
        f"     support                             : {report.unsupported_sentences}",
        f"  3. uncited claims in no retrieved chunk: {report.uncited_claims}",
        "",
        f"  (uncited but present in a chunk)       : {report.missing_markers}",
        f"  (lexically ambiguous, needs a human)   : {report.needs_human}",
    ]
    failures = report.failures()[:examples]
    if failures:
        lines += ["", "  examples:"]
        for bad in failures:
            marks = ",".join(str(m) for m in bad.markers) or "-"
            lines.append(
                f"    [{marks}] {bad.verdict:<14} cited={bad.overlap:.2f} "
                f"best={bad.best_in_pool:.2f}({bad.pool_match or '-'})  {bad.sentence[:70]}"
            )
    return "\n".join(lines)
