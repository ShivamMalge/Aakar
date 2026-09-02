"""SceneSpec generation (3B).

A chapter plus its 3A structure set in; a SceneSpec out — parsed strictly, validated
referentially, and with every provenance claim re-checked against the chunk text before
anyone reads a number.

The two things this package is built to make visible rather than hide:

* **Whether the model can hold the schema at all.** Schema-valid-on-first-attempt and
  referential-valid rates are measured per topic over repeated generations, with no repair
  and no silent retry. A model that cannot hold the schema is a finding, and the escalation
  is proposed, not performed (3B.4).
* **Whether provenance is honest.** `chunk_ids` may be empty (schema 1.2, D-025). A part
  the chapter never asserts must carry empty provenance, and a citation to a chunk that
  does not name the part is a fabrication, counted per part by the same whole-word matcher
  provenance resolution uses. If zero-provenance parts never occur, that is a finding and a
  stop, not a pass (3B gate).

Parent relations are scene-graph attachment only (D-031). The generator is told so; the
containment relation is derived by `compile()` downstream and is never asserted here.
"""

from .compare import Comparison, compare_to_golden
from .generate import GenerationOutcome, classify, generate, verify_provenance
from .prompt import SYSTEM, build_prompt

__all__ = [
    "SYSTEM",
    "Comparison",
    "GenerationOutcome",
    "build_prompt",
    "classify",
    "compare_to_golden",
    "generate",
    "verify_provenance",
]
