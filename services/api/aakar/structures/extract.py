"""Structure extraction: the model proposes, the code decides (3A.1, 3A.2).

One chat call per chapter. The model returns entities with a kind, the chunks it believes
name each, its surface forms as written, synonyms and abbreviations, and a `modellable`
guess for the topic's scale. **None of that is trusted as-is.** Every claim goes through
the deterministic half (`verify.py`):

1. `kind` outside the vocabulary → dropped (R0).
2. Every claimed surface form is checked against the chapter, whole-word; a form the
   chapter never contains is dropped and reported. Rule-generated inflections are added
   from the name and from every synonym that passes the precision guard.
3. Naming chunks are **computed by the matcher**, not copied from the model. The model's
   claims are scored against that as a diagnostic (confirmed / dropped / missed). An entity
   no chunk names is dropped: the model invented it.
4. The generic-mention rule R1 is applied over the forms the chapter actually uses, so the
   extractor and the label set draw the boundary in the same place by construction.
5. The whole alias set is checked for collisions across entities (R3). A collision **fails
   the extraction** — `CollisionError` carries the full list — rather than picking a
   winner. Silent resolution here surfaces later as provenance behaviour nobody can
   explain (architect ruling, D-063).

Precision is therefore protected by construction; recall is what the gate measures.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from aakar.providers import ChatRequest, Provider, Usage

from .inflect import inflections, normalise
from .verify import (
    Collision,
    confirm_naming_chunks,
    find_collisions,
    is_generic_mention,
    mentions,
    naming_chunks_for,
    singular_candidates,
    synonym_rejection,
)

KIND_VOCABULARY = ("structure", "region", "cell_type", "substance", "molecule")

SYSTEM = """You extract the named anatomical or structural entities from a chapter of a \
student's textbook. You work ONLY from the numbered passages you are given.

Rules:
1. List every distinct physical constituent the passages NAME: structures, regions, cell \
types, substances, molecules. Not processes, not properties, not external stimuli.
2. Two names for one thing are ONE entity. Put the extra names in "synonyms".
3. For each entity, list the ids of the passages that name it, and copy each surface form \
EXACTLY as it appears in the text (including plurals and abbreviations such as "RGCs").
4. Give synonyms and abbreviations you know for the entity even if the passages do not use \
them. Do not invent entities the passages never name.
5. "kind" must be one of: structure, region, cell_type, substance, molecule.
6. "modellable" means: could a 3D model of the WHOLE topic at the scale given reasonably \
include this as a distinct clickable part? A whole-eye model includes the lens; it does not \
include individual photoreceptor cells.

Answer with JSON only, no prose, no code fences:
{"entities": [{"name": "...", "kind": "...", "naming_chunk_ids": ["..."], \
"surface_forms_in_text": ["..."], "synonyms": ["..."], "abbreviations": ["..."], \
"modellable": true}]}"""


@dataclass(frozen=True)
class Alias:
    form: str
    #: ``rule`` (deterministic inflection) | ``model`` (synonym or abbreviation) |
    #: ``text`` (a surface form the model copied from the chapter, confirmed present).
    source: str


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    kind: str
    modellable: bool
    aliases: tuple[Alias, ...]
    #: Forms that actually occur in the chapter, whole-word. A subset of the aliases.
    forms_in_chapter: tuple[str, ...]
    #: Computed by the matcher over every alias; the authoritative list.
    naming_chunks: tuple[str, ...]
    pages: tuple[str, ...]
    #: The model's own chunk claims, scored: what it got right, what it made up, what it
    #: missed. A diagnostic on the model, not part of the output the gate reads.
    claims_confirmed: tuple[str, ...]
    claims_dropped: tuple[str, ...]
    claims_missed: tuple[str, ...]

    @property
    def all_forms(self) -> tuple[str, ...]:
        return (self.name, *(a.form for a in self.aliases))


@dataclass(frozen=True)
class Dropped:
    name: str
    rule: str
    detail: str


@dataclass
class Extraction:
    entities: list[ExtractedEntity] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    rejected_synonyms: list[tuple[str, str, str]] = field(default_factory=list)
    unverifiable_forms: list[tuple[str, str]] = field(default_factory=list)
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    raw_entity_count: int = 0

    @property
    def usd(self) -> float:
        return self.usage.usd


class ParseFailure(RuntimeError):
    """The model did not return the JSON it was asked for. Not retried: reported (3B.4)."""


class CollisionError(RuntimeError):
    """R3. Two entities claim one surface form. The extraction is refused whole."""

    def __init__(self, collisions: Sequence[Collision]) -> None:
        self.collisions = tuple(collisions)
        listed = "; ".join(f"{c.form!r} <- {', '.join(c.entities)}" for c in collisions)
        super().__init__(f"alias collision(s), extraction refused: {listed}")


def build_prompt(chunks: Mapping[str, tuple[str, str]], topic_scale: str) -> str:
    """`chunks` is id -> (page_label, text). Passages carry their id and page so the model
    can cite by id and the output can carry the label the student will see (2A.6)."""
    passages = "\n\n".join(f"[{cid}] (p. {page}) {text}" for cid, (page, text) in chunks.items())
    return (
        f"Topic scale for 'modellable': {topic_scale}\n\nPassages:\n\n{passages}\n\n"
        "Return the JSON now."
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_response(text: str) -> list[dict[str, object]]:
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ParseFailure(f"not JSON: {exc}; first 200 chars: {cleaned[:200]!r}") from None
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, list):
        raise ParseFailure("JSON has no 'entities' list")
    return [e for e in entities if isinstance(e, dict)]


def _strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


class _AliasCollector:
    """Deduplicates aliases on the normalised key and never admits the name itself. A
    class rather than a closure so the loop it serves has no late-binding trap."""

    def __init__(self, name: str) -> None:
        self._own = normalise(name)
        self._seen: dict[str, Alias] = {}

    def add(self, form: str, source: str) -> None:
        key = normalise(form)
        if key and key != self._own and key not in self._seen:
            self._seen[key] = Alias(form=form.strip(), source=source)

    @property
    def aliases(self) -> list[Alias]:
        return list(self._seen.values())


def decide(
    proposed: Sequence[Mapping[str, object]],
    chunks: Mapping[str, tuple[str, str]],
    *,
    category_nouns: frozenset[str],
    guard: str = "approved",
    recover_singulars: bool = False,
) -> Extraction:
    """The deterministic half, separated from the model call so it is testable in replay
    against hand-written proposals — including ones built to be refused (R2).

    `guard` selects the synonym precision guard: ``approved`` is D-063 as ruled; ``refined``
    is the alternative measured after the first live run showed the approved guard rejecting
    *photoreceptor* for "Photoreceptor cell" (D-067). Measured side by side; not switched.

    `recover_singulars`: the second alternative. For a plural the model copied from the
    text, also emit its singular when the chapter contains that singular whole-word — so
    "rods" recovers "rod" from "the rod photoreceptor". Corpus-checked, so it cannot invent
    a form; still a change to the approved method, so measured and not switched.
    """
    texts = {cid: text for cid, (_page, text) in chunks.items()}
    chapter_text = " ".join(texts.values())
    result = Extraction(raw_entity_count=len(proposed))
    names = [str(p.get("name", "")).strip() for p in proposed]

    for raw in proposed:
        name = str(raw.get("name", "")).strip()
        if not name:
            result.dropped.append(Dropped("", "parse", "entity with no name"))
            continue
        kind = str(raw.get("kind", "")).strip()
        if kind not in KIND_VOCABULARY:
            result.dropped.append(Dropped(name, "R0", f"kind {kind!r} not in vocabulary"))
            continue

        collector = _AliasCollector(name)
        # Sorted: `inflections` is a set, and set order varies per process under hash
        # randomisation. The collector keeps the first of two forms that share a normalised
        # key, so unsorted iteration made the emitted spelling of an alias differ between a
        # recording and its replay (found by diffing the two, D-067).
        for form in sorted(inflections(name)):
            collector.add(form, "rule")

        others = [n for n in names if n and n != name]
        for synonym in _strings(raw.get("synonyms")) + _strings(raw.get("abbreviations")):
            reason = synonym_rejection(
                name, synonym, others, category_nouns=category_nouns if guard == "refined" else None
            )
            if reason:
                result.rejected_synonyms.append((name, synonym, reason))
                continue
            collector.add(synonym, "model")
            for form in sorted(inflections(synonym)):
                collector.add(form, "rule")

        # Surface forms the model says it saw. Kept only if the chapter really contains
        # them: this is the "never harvest" discipline applied to the model's own eyes.
        for form in _strings(raw.get("surface_forms_in_text")):
            if mentions(chapter_text, [form]):
                collector.add(form, "text")
                if recover_singulars:
                    for candidate in singular_candidates(form):
                        if mentions(chapter_text, [candidate]):
                            collector.add(candidate, "text")
            else:
                result.unverifiable_forms.append((name, form))

        all_forms = (name, *(a.form for a in collector.aliases))
        forms_in_chapter = tuple(f for f in all_forms if mentions(chapter_text, [f]))
        naming = naming_chunks_for(all_forms, texts)
        if not naming:
            result.dropped.append(Dropped(name, "not_named", "no passage contains any form"))
            continue

        if is_generic_mention(forms_in_chapter, chapter_text, category_nouns):
            result.dropped.append(
                Dropped(name, "R1", f"generic mention: forms {list(forms_in_chapter)}")
            )
            continue

        claimed = _strings(raw.get("naming_chunk_ids"))
        confirmed, dropped_claims = confirm_naming_chunks(all_forms, texts, claimed)
        missed = tuple(c for c in naming if c not in confirmed)

        result.entities.append(
            ExtractedEntity(
                name=name,
                kind=kind,
                modellable=bool(raw.get("modellable", False)),
                aliases=tuple(collector.aliases),
                forms_in_chapter=forms_in_chapter,
                naming_chunks=naming,
                pages=tuple(dict.fromkeys(chunks[c][0] for c in naming)),
                claims_confirmed=confirmed,
                claims_dropped=dropped_claims,
                claims_missed=missed,
            )
        )

    collisions = find_collisions({e.name: e.all_forms for e in result.entities})
    if collisions:
        raise CollisionError(collisions)
    return result


def extract(
    provider: Provider,
    chunks: Mapping[str, tuple[str, str]],
    *,
    model: str,
    topic_scale: str,
    category_nouns: frozenset[str],
    max_tokens: int = 8192,
) -> Extraction:
    """One model call, then `decide`. Cost is whatever the provider reports."""
    response = provider.chat(
        ChatRequest(
            model=model,
            system=SYSTEM,
            prompt=build_prompt(chunks, topic_scale),
            max_tokens=max_tokens,
        )
    )
    proposed = parse_response(response.text)
    result = decide(proposed, chunks, category_nouns=category_nouns)
    result.model = model
    result.usage = response.usage
    return result
