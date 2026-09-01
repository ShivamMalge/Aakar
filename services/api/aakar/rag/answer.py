"""The answer tier (2D.1b): prose over retrieved chunks, with inline citation markers.

## Markers, not prose citations

The model emits `[1]`, `[2]` — indices into the chunk list it was given, **not** page
numbers. The mapping from marker to page LABEL happens in code, after the fact.

That is deliberate and it is what makes the faithfulness eval possible. If the model wrote
`[p. 543]` directly there would be nothing to check: a hallucinated page number is
indistinguishable from a real one, and the eval could only ask "is this a plausible page",
which is not a question with an answer. A marker points at a specific retrieved chunk, so
"does chunk 2 support this sentence" is decidable by reading chunk 2.

## The prompt is a contract, not an instruction

Every rule below has a corresponding count in `evals/faithfulness.py`. A rule the eval
cannot measure is a wish, and the eval is the deliverable here — the prompt is the part
that is easy to change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .index import Hit

SYSTEM = """You answer questions about a student's own textbook chapter, using ONLY the \
numbered passages you are given.

Rules, all of which are checked automatically:

1. Every sentence that makes a factual claim MUST end with a citation marker like [1] or \
[2,3], naming the passage or passages that state it.
2. A marker may only name a passage from the list below. Never invent a number.
3. The passage you cite must actually state the claim. Do not cite a passage that merely \
mentions the same structure.
4. If the passages do not answer the question, say so plainly and stop. Do not supply the \
answer from general knowledge, and do not pad with what the passages do say instead.
5. Do not write page numbers. Use passage numbers only; the page reference is added later.

Answer in 2-4 sentences of plain prose. No preamble, no bullet points, no restating the \
question."""


@dataclass(frozen=True)
class AnswerPrompt:
    system: str
    user: str
    #: Marker index (1-based, as the model sees it) -> the chunk it refers to.
    numbering: dict[int, Hit]


def build_prompt(question: str, hits: Sequence[Hit]) -> AnswerPrompt:
    """Number the passages and lay them out.

    1-based because that is how a reader counts, and a model that miscounts from zero
    produces off-by-one citations that look right — the hardest kind to spot.
    """
    numbering = {i: hit for i, hit in enumerate(hits, start=1)}
    passages = "\n\n".join(f"[{i}] {hit.text}" for i, hit in numbering.items())
    user = f"Passages from the student's chapter:\n\n{passages}\n\nQuestion: {question}"
    return AnswerPrompt(system=SYSTEM, user=user, numbering=numbering)
