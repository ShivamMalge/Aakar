"""Deterministic inflection generation (3A.2, D-063).

**Generate, then check. Never harvest.** A stem-prefix harvest over the golden chapter
proposed `nervous` for *optic nerve* and `photosensitive` for *photoreceptor*. A false alias
whole-word-matches a chunk that never names the part and promotes provenance to `strong` —
the fabricated-confidence failure D-030 exists to prevent. So every alias here is produced
by a rule from the entity's own name, and nothing is pulled from text by similarity.

**Generate broadly** (architect ruling, D-065). Over-generating Latin plurals is safe
precisely because generation is followed by a check and R3 forbids collisions between
entities: *retinae* costs nothing if the chapter never says it. The one boundary is that a
generated form must not be a real *unrelated* word — R3 catches collisions between
entities, not between an entity and ordinary vocabulary. Latin plurals and `-or/-our`
cannot produce such a word; prefix variants (`oe`/`e`) could, and are left out on that
ground.

Matching downstream is case-insensitive and whole-word (`verify.mentions`), so forms are
emitted lowercase except abbreviations, which keep their case so `RGCs` stays readable.
"""

from __future__ import annotations

import re

#: Latin/Greek endings common in anatomy. Each rule is (suffix, replacements). Several
#: replacements per suffix on purpose: *-us* is *alveolus→alveoli* and *corpus→corpora*
#: and *genus→genera*; the wrong ones for a given word simply never occur in a chapter.
CLASSICAL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix", ("ices",)),  # appendix -> appendices; before -x
    ("ex", ("ices",)),  # cortex -> cortices
    ("is", ("es", "ides")),  # testis -> testes; iris -> irides
    ("us", ("i", "era", "ora")),  # alveolus -> alveoli; genus -> genera; corpus -> corpora
    ("um", ("a",)),  # septum -> septa
    ("on", ("a",)),  # ganglion -> ganglia
    ("ma", ("mata",)),  # stoma -> stomata
    ("a", ("ae",)),  # vertebra -> vertebrae; retina -> retinae (unused, harmless)
    ("x", ("ces",)),  # thorax -> thoraces
)

SIBILANT = ("s", "x", "z", "ch", "sh")


def normalise(form: str) -> str:
    """The comparison key: lowercase, hyphens and runs of space collapsed to one space."""
    return re.sub(r"[\s\-]+", " ", form.strip()).lower()


def _english_plurals(word: str) -> set[str]:
    out = {word + "s"}
    if word.endswith(SIBILANT):
        out.add(word + "es")
    if len(word) > 2 and word.endswith("y") and word[-2] not in "aeiou":
        out.add(word[:-1] + "ies")
    if word.endswith("fe"):
        out.add(word[:-2] + "ves")
    elif word.endswith("f"):
        out.add(word[:-1] + "ves")
    return out


def _classical_plurals(word: str) -> set[str]:
    out: set[str] = set()
    for suffix, replacements in CLASSICAL:
        if len(word) > len(suffix) + 1 and word.endswith(suffix):
            stem = word[: -len(suffix)]
            out.update(stem + r for r in replacements)
    return out


def _spelling_variants(word: str) -> set[str]:
    """British/American pairs a chapter might use either way. Only endings that cannot
    turn the word into an unrelated one."""
    out: set[str] = set()
    if word.endswith("or") and len(word) > 4:
        out.add(word[:-2] + "our")  # humor -> humour
    if word.endswith("our") and len(word) > 5:
        out.add(word[:-3] + "or")  # humour -> humor
    if word.endswith("ise") and len(word) > 4:
        out.add(word[:-3] + "ize")
    if word.endswith("ize") and len(word) > 4:
        out.add(word[:-3] + "ise")
    return out


def _is_abbreviation(token: str) -> bool:
    return len(token) >= 2 and token.isupper()


def _head_variants(head: str) -> set[str]:
    """Every inflection of one word. Spelling variants are inflected too, so *humour*
    yields *humours* and not only *humor* -> *humors*."""
    if _is_abbreviation(head):
        return {head, head + "s"}
    base = head.lower()
    spellings = {base} | _spelling_variants(base)
    out: set[str] = set()
    for word in spellings:
        out.add(word)
        out |= _english_plurals(word)
        out |= _classical_plurals(word)
    return out


def inflections(name: str) -> set[str]:
    """All rule-generated surface forms of an entity name, including the name itself.

    Multiword names inflect on the head (last token) and additionally vary hyphen/space
    joins on the whole phrase, so *membrane-bound disc* covers *membrane bound discs*.
    """
    name = name.strip()
    if not name:
        return set()
    tokens = re.split(r"[\s\-]+", name)
    head, modifiers = tokens[-1], tokens[:-1]
    forms: set[str] = set()
    for variant in _head_variants(head):
        if modifiers:
            prefix = " ".join(m if _is_abbreviation(m) else m.lower() for m in modifiers)
            forms.add(f"{prefix} {variant}")
            forms.add(f"{prefix}-{variant}")
            if "-" in name:
                # Keep the original hyphenation as written, inflected.
                original_prefix = name[: name.rfind(tokens[-1])].rstrip()
                forms.add(
                    f"{original_prefix}{variant}"
                    if original_prefix.endswith("-")
                    else f"{original_prefix} {variant}"
                )
        else:
            forms.add(variant)
    return forms
