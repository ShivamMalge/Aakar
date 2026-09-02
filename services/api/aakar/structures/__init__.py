"""Chapter structure extraction (3A).

What the chapter names, with the chunk and page that names each thing, and the aliases
under which provenance will recognise it. This is the coverage baseline the curation gate
reads: "9 structures named in the chapter, 6 present in the spec" needs the 9 first, and
that is its own extraction task with its own accuracy question (phases.md, 3A).

Division of labour, fixed by D-063 and D-064:

* **The model proposes.** Entities, their kind, the chunks that name them, synonyms and
  abbreviations. One call per chapter.
* **Code verifies and decides.** Every claimed naming chunk is re-checked with the same
  whole-word matcher provenance uses; unconfirmed claims are dropped. The label rules
  (R0-R3) are applied mechanically. Inflections come from a deterministic generator, never
  from the model and never harvested from the text by similarity.
* **A collision is a defect.** Two entities claiming one surface form fails extraction
  outright rather than picking a winner (R3).

Nothing in this package can spend money on its own: the only model call goes through
`Provider`, under the cassette and the ledger.
"""

from .inflect import inflections, normalise
from .labels import StructureLabels, load_labels
from .verify import (
    Collision,
    confirm_naming_chunks,
    find_collisions,
    is_generic_mention,
    mentions,
    occurrences,
    synonym_rejection,
)

__all__ = [
    "Collision",
    "StructureLabels",
    "confirm_naming_chunks",
    "find_collisions",
    "inflections",
    "is_generic_mention",
    "load_labels",
    "mentions",
    "normalise",
    "occurrences",
    "synonym_rejection",
]
