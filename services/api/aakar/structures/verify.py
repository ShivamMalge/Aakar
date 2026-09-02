"""The deterministic half of extraction: matching, the label rules, and the collision check.

Everything here is a pure function of text and names. No model, no key, no network — which
is what lets the rules be tested exhaustively in replay and lets a verifier reproduce every
label by hand.

**One matcher.** `mentions` is the same whole-word, case-insensitive test provenance
resolution uses (D-030). The extractor confirming a naming chunk, the label rules counting
occurrences, and provenance later crediting a part must all agree on what "names" means, or
the coverage baseline will say a structure is named where provenance later says it is not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .inflect import normalise


def _pattern(form: str) -> re.Pattern[str]:
    # Hyphens in a form match either a hyphen or a space in the text, so "membrane-bound
    # disc" finds "membrane bound disc" and vice versa.
    escaped = re.escape(form.strip().lower()).replace(r"\-", r"[\s\-]").replace(r"\ ", r"[\s\-]+")
    return re.compile(rf"\b{escaped}\b")


def mentions(text: str, forms: Iterable[str]) -> bool:
    """Whole-word, case-insensitive. The single definition of "the chunk names it"."""
    lowered = text.lower()
    return any(form and _pattern(form).search(lowered) for form in forms)


def occurrences(text: str, forms: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(len(_pattern(form).findall(lowered)) for form in forms if form)


# ------------------------------------------------------------------ the label rules


#: R1(c). Each is a template with ``X`` where the surface form goes.
DEFAULT_NAMING_CONSTRUCTIONS: tuple[str, ...] = (
    r"\bcalled (?:the |a |an )?X\b",
    r"\bknown as (?:the |a |an )?X\b",
    r"\btermed (?:the |a |an )?X\b",
    r"\breferred to as (?:the |a |an )?X\b",
    r"\bor (?:the |a |an )?X\b\s*,",
)


def is_named_by_construction(
    text: str, forms: Iterable[str], constructions: Sequence[str] = DEFAULT_NAMING_CONSTRUCTIONS
) -> bool:
    lowered = text.lower()
    for form in forms:
        target = re.escape(form.lower()).replace(r"\ ", r"[\s\-]+")
        if any(re.search(c.replace("X", target), lowered) for c in constructions):
            return True
    return False


def head_noun(form: str) -> str:
    """The last token, hyphen-split: the head of "membrane-bound disc" is "disc"."""
    tokens = re.split(r"[\s\-]+", form.strip())
    return tokens[-1].lower() if tokens else ""


def is_generic_mention(
    forms: Sequence[str],
    chapter_text: str,
    category_nouns: frozenset[str],
    constructions: Sequence[str] = DEFAULT_NAMING_CONSTRUCTIONS,
) -> bool:
    """R1 (D-064). Excluded iff every surface form has a category-noun head AND total
    occurrences <= 1 AND no occurrence is introduced by a naming construction.

    Evaluated over the surface forms the chapter uses, not a canonical name: on
    "retinal ganglion cell" the head is "cell" and the rule would exclude it; on "RGCs",
    the only form the chapter writes, it does not. The rule is about how the chapter names
    the thing. The asymmetry this creates — a non-category head is included at any count —
    is recorded in the label set and kept deliberately (D-065).
    """
    if not forms:
        return True
    all_category = all(
        head_noun(f) in category_nouns or head_noun(f).rstrip("s") in category_nouns for f in forms
    )
    if not all_category:
        return False
    if occurrences(chapter_text, forms) > 1:
        return False
    return not is_named_by_construction(chapter_text, forms, constructions)


def confirm_naming_chunks(
    forms: Iterable[str], chunks: Mapping[str, str], claimed: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The verifier. Returns (confirmed, dropped).

    A claimed chunk is kept only if the chunk's text actually contains one of the entity's
    surface forms, whole-word. The model proposes; this decides. A claim that cannot be
    confirmed is dropped and reported, never kept on the model's word — that is the entire
    difference between provenance and citation theatre.
    """
    forms = tuple(forms)
    confirmed: list[str] = []
    dropped: list[str] = []
    for chunk_id in claimed:
        text = chunks.get(chunk_id)
        if text is not None and mentions(text, forms):
            confirmed.append(chunk_id)
        else:
            dropped.append(chunk_id)
    return tuple(confirmed), tuple(dropped)


def naming_chunks_for(forms: Iterable[str], chunks: Mapping[str, str]) -> tuple[str, ...]:
    """Every chunk that names the entity, in chunk order. What the verifier can add back:
    a chunk the model did not claim but which plainly names the thing."""
    forms = tuple(forms)
    return tuple(cid for cid, text in chunks.items() if mentions(text, forms))


def singular_candidates(form: str) -> tuple[str, ...]:
    """Stems a confirmed plural might have come from. Deliberately naive: every candidate
    is only kept by the caller if the CHAPTER contains it whole-word, so "lens" -> "len"
    is proposed and discarded rather than never proposed and never wrong."""
    low = form.strip().lower()
    out: list[str] = []
    if low.endswith("ies"):
        out.append(low[:-3] + "y")
    if low.endswith("es"):
        out.append(low[:-2])
    if low.endswith("s"):
        out.append(low[:-1])
    return tuple(dict.fromkeys(c for c in out if len(c) > 2))


# ------------------------------------------------------------------ R3 and the guard


@dataclass(frozen=True)
class Collision:
    form: str
    entities: tuple[str, ...]


def find_collisions(claims: Mapping[str, Iterable[str]]) -> list[Collision]:
    """R3. Every surface form claimed by more than one entity, by any route.

    Compared on the normalised key so "membrane-bound disc" and "membrane bound disc" are
    the same claim. Returns a list rather than raising: the caller decides whether this is
    a label-set defect or an extraction failure, and both need the full list, not the first.
    """
    seen: dict[str, list[str]] = {}
    for entity, forms in claims.items():
        for form in forms:
            key = normalise(form)
            if key and entity not in seen.setdefault(key, []):
                seen[key].append(entity)
    return [Collision(form=k, entities=tuple(v)) for k, v in sorted(seen.items()) if len(v) > 1]


def synonym_rejection(
    entity: str,
    synonym: str,
    other_entities: Iterable[str],
    *,
    category_nouns: frozenset[str] | None = None,
) -> str | None:
    """The precision guard on model synonyms (D-063). Returns why it is rejected, or None.

    As approved: rejects a single-token synonym that is a token inside its own multiword
    name ("body" for *ciliary body*) or the head of a *different* entity — the class of
    synonym that whole-word-matches other structures' chunks.

    With `category_nouns` given, the own-name rule is REFINED (D-067, measured, not
    switched): the token is rejected only when it is itself a category noun. "body" in
    *ciliary body* still falls; "photoreceptor" in *Photoreceptor cell* — where the token is
    the distinguishing term and "cell" is the category — passes. The first live run showed
    the approved rule rejecting exactly that, and the singular form going uncovered.
    """
    key = normalise(synonym)
    if not key:
        return "empty"
    own_tokens = set(normalise(entity).split())
    if key == normalise(entity):
        return "identical to the name"
    if " " not in key:
        own_token = key in own_tokens and len(own_tokens) > 1
        if own_token and (category_nouns is None or key in category_nouns):
            return f"{synonym!r} is a token inside its own name {entity!r}"
        for other in other_entities:
            if normalise(other) != normalise(entity) and head_noun(other) == key:
                return f"{synonym!r} is the head noun of another entity, {other!r}"
    return None
