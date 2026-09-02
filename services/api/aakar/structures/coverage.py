"""The coverage baseline (3A.3): what the curation gate reads.

"9 structures named in the chapter, 6 present in the spec" is two numbers, and this file is
the first one. It carries, per entity, everything the gate and 3B need and nothing they do
not: the name, kind, `modellable`, the aliases provenance will recognise (with their
source), the chunks and page labels that name it.

`modellable` is what lets the gate split "named and omitted" (a defect the curator acts on)
from "named and out of scope" (correct, not the curator's problem) — D-064. The
`omitted` denominator downstream is `modellable: true` entities only.

**The model's guess is `modellable_proposed`, and 3B does not read it** (ruling, D-068).
25/27 agreement with the verified labels was misleading: both disagreements were the
humours, the exact class where the judgement was hardest. A signal systematically wrong on
the difficult class is worse than no signal in a coverage denominator. It stays recorded as
a proposal a second chapter may later measure it against.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .extract import Extraction


def baseline(extraction: Extraction, *, chapter_id: str, topic_scale: str) -> dict[str, Any]:
    """A JSON-serialisable record. Dropped entities are carried too: the gate should be
    able to show a curator *why* something the model proposed is not on the list."""
    return {
        "chapter_id": chapter_id,
        "topic_scale": topic_scale,
        "model": extraction.model,
        "usd": extraction.usd,
        "named": len(extraction.entities),
        "named_modellable_proposed": sum(e.modellable for e in extraction.entities),
        "entities": [
            {
                "name": e.name,
                "kind": e.kind,
                "modellable_proposed": e.modellable,
                "aliases": [asdict(a) for a in e.aliases],
                "forms_in_chapter": list(e.forms_in_chapter),
                "naming_chunks": list(e.naming_chunks),
                "pages": list(e.pages),
            }
            for e in extraction.entities
        ],
        "dropped": [asdict(d) for d in extraction.dropped],
        "rejected_synonyms": [
            {"entity": n, "synonym": s, "reason": r} for n, s, r in extraction.rejected_synonyms
        ],
        "unverifiable_forms": [{"entity": n, "form": f} for n, f in extraction.unverifiable_forms],
    }


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"
