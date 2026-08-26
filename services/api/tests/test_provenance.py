"""Derived provenance strength (D-025, schema 1.2) — Python side.

Driven by packages/scenespec/fixtures/provenance/, the same files the zod mirror uses.

The change this tests is the one that matters most for Rule 6: `chunk_ids` may now be
empty. Requiring at least one citation was safe for hand-authored specs and unsafe for
generated ones — a model proposing a part the chapter does not mention was forced to cite
the nearest plausible chunk, so the schema made fabricated provenance *mandatory*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aakar.scenespec import (
    SceneSpec,
    assert_parse_time,
    parse_scene_spec,
    provenance_strengths,
    strength_counts,
    ungrounded_parts,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DIR = REPO_ROOT / "packages/scenespec/fixtures/provenance"
FILES = sorted(DIR.glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_fixtures_cover_both_parse_states() -> None:
    """`weak` and `strong` are absent by design — unreachable without corpus text."""
    seen = {state for p in FILES for state in _load(p)["expect"].values()}
    assert seen == {"none", "unverified"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_strength_matches_the_fixture(path: Path) -> None:
    fixture = _load(path)
    assert provenance_strengths(fixture["spec"]) == fixture["expect"], fixture["note"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_the_document_still_parses(path: Path) -> None:
    """Zero provenance is legal, not an error — the whole point of D-025."""
    fixture = _load(path)
    result = parse_scene_spec(fixture["spec"])
    assert result.ok, result.errors
    assert result.provenance_strength == fixture["expect"]


def test_empty_chunk_ids_is_accepted_by_the_schema() -> None:
    """Before schema 1.2 this raised. It is the state the curation gate needs to show."""
    document = {
        "schema_version": "1.2",
        "topic": "zero_provenance",
        "title": "Zero provenance",
        "parts": [
            {
                "id": "invented",
                "name": "Invented",
                "geometry": {"type": "sphere", "radius": 1},
                "material": {"color": "#aabbcc"},
                "provenance": {"chunk_ids": []},
            }
        ],
    }
    SceneSpec.model_validate(document)
    assert parse_scene_spec(document).ok


def test_strength_is_not_author_supplied() -> None:
    """`provenance_strength` is derived. A spec trying to set it must be rejected."""
    document = _load(DIR / "unverified-cited-and-quoted.json")["spec"]
    document["parts"][0]["provenance_strength"] = "strong"
    result = parse_scene_spec(document)
    assert not result.ok
    assert any(
        "extra" in issue.code or "forbidden" in issue.message.lower() for issue in result.issues
    )


def test_counts_and_ungrounded_ids() -> None:
    spec = _load(DIR / "mixed-both-parse-states.json")["spec"]
    assert strength_counts(spec) == {"unverified": 2, "none": 1}
    assert ungrounded_parts(spec) == ["invented"]


def test_evidence_does_not_buy_a_verified_strength() -> None:
    """The point of D-030.

    A quotation the author supplied is still the author's claim about a chunk nobody has
    read. Deriving `strong` from it would be fabricated confidence, and every consumer
    between parse and D-008's check would see an unearned claim.
    """
    quoted = _load(DIR / "unverified-cited-and-quoted.json")["spec"]
    bare = _load(DIR / "unverified-cited-without-quote.json")["spec"]
    assert provenance_strengths(quoted) == {"lens": "unverified"}
    assert provenance_strengths(bare) == {"lens": "unverified"}


def test_parse_refuses_a_verified_strength() -> None:
    """Typing alone would not catch a value from JSON, storage, or a premature resolver."""
    assert assert_parse_time({"a": "unverified", "b": "none"}) == []
    assert assert_parse_time({"a": "strong"}) == [("a", "strong")]
    assert assert_parse_time({"a": "weak"}) == [("a", "weak")]


def test_golden_specs_are_unverified_until_backfill() -> None:
    """D-003's sentinel cites a reserved id, so the golden specs are uniformly unverified.

    Phase 2B task 2B.11 backfills real chunk ids, and the D-008 check then resolves them.
    """
    for path in sorted((REPO_ROOT / "specs/golden").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        counts = strength_counts(document)
        assert counts["none"] == 0, f"{path.stem} has an uncited part"
        assert counts["unverified"] == len(document["parts"])
