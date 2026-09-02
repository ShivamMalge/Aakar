"""The generation prompt (3B.1). Constrained emission against the schema.

The model is given four things and told exactly what each is for:

1. **The JSON Schema, verbatim.** Not a paraphrase — the closed geometry vocabulary and
   every parameter name come from the same file the validator reads (D7).
2. **One golden spec from a DIFFERENT topic** as a shape exemplar. Never the target topic's
   own golden spec: the gate compares the generation against it, and a model that has seen
   the answer is not being measured.
3. **The chapter's passages**, each with its chunk id and page label, because `chunk_ids`
   must name real chunks and nothing else.
4. **The 3A structure set** — what the chapter names, with the chunks that name each — so
   the model has the coverage baseline in front of it and cannot claim ignorance of a
   structure the chapter discusses.

Two rules are stated more than once because they are the ones a fluent model breaks first:
**cite only chunks that name the part, and leave `chunk_ids` empty when none does**; and
**`parent_id` is scene-graph attachment, not containment** (D-031).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

SYSTEM = """You write a SceneSpec: a JSON document describing a labeled, clickable 3D model \
of ONE topic from a student's textbook chapter, for a deterministic renderer. Every part \
must be one of the nine geometry types in the schema; there are no meshes and no imports.

The document you produce is validated by machine against the JSON Schema you are given, \
then every provenance claim is checked against the chapter text. So:

1. OUTPUT ONLY JSON matching the schema exactly. No prose, no code fences, no comments, \
no extra keys. Use the parameter names the schema uses.
2. PROVENANCE IS CHECKED. `provenance.chunk_ids` for a part may list ONLY chunk ids whose \
passage actually names that part. If no passage names it, use an EMPTY list []. An empty \
list is a correct and expected answer for a part you include from general knowledge; a \
citation to a passage that does not name the part is a fabrication and is counted.
3. `parent_id` means the part's transform is expressed relative to that parent and moves \
with it (a scene-graph attachment). It does NOT mean "is inside" or "is part of"; \
containment is derived from the geometry by the renderer. Most parts have no parent. Use a \
parent only when a part is physically attached to and moves with another (a fovea on the \
retina; a nucleolus in the nucleus is NOT a reason).
4. Part ids: lowercase snake_case, unique, ASCII. `name` is what the student sees. \
`aliases` are other names the chapter or a student might use — drive retrieval, so include \
the inflections and synonyms the structure set lists.
5. Model the topic at the scale given. Omit structures below that scale rather than \
forcing them in; the structure set marks which are modellable at this scale.
6. Keep the whole model within a bounding region of roughly 3 units so the camera hint \
frames it. Nested layers must differ in radius so the cutaway shows them.
7. At most 40 parts. Prefer the structures the chapter actually names.

Return the JSON document now."""


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def build_prompt(
    *,
    schema: Mapping[str, Any],
    exemplar: Mapping[str, Any],
    exemplar_note: str,
    topic: str,
    title: str,
    scale: str,
    chunks: Mapping[str, tuple[str, str]],
    structures: Sequence[Mapping[str, Any]],
    nonce: str = "",
) -> str:
    """`chunks` is id -> (page_label, text). `structures` is the 3A baseline's entity list.

    `nonce` exists for measurement only: repeated generations of an identical request replay
    from one cassette, so a run index is folded into the prompt to make each trial a
    distinct recording. It changes nothing the model is asked to do.
    """
    passages = "\n".join(f"[{cid}] (p. {page}) {text}" for cid, (page, text) in chunks.items())
    named = "\n".join(
        f"- {s['name']} (kind: {s['kind']}; named in: {', '.join(s['naming_chunks'])}"
        f"; aliases: {', '.join(a['form'] for a in s.get('aliases', [])[:6]) or '-'})"
        for s in structures
    )
    parts = [
        f"JSON SCHEMA (authoritative):\n{_compact(schema)}",
        f"EXEMPLAR SPEC — a different topic, for shape only ({exemplar_note}):\n"
        f"{_compact(exemplar)}",
        f"TOPIC: {topic}\nTITLE: {title}\nSCALE: {scale}",
        f"CHAPTER PASSAGES (the only citable sources; cite by id):\n{passages}",
        f"STRUCTURES THE CHAPTER NAMES (from extraction; with the chunks that name them):\n{named}",
    ]
    if nonce:
        parts.append(f"(trial {nonce})")
    return "\n\n".join(parts)
