"""Referential constraints — Python side, driven by the shared fixture set.

The mirror of apps/web/src/scenespec/referential.test.ts, over the same files in
packages/scenespec/fixtures/referential/. The cross-stack contract is the (code, path)
pair; message text is each stack's own business.

This suite is the reason the constraints moved out of the TypeScript compiler: Phase 3's
generator parses and stores a spec server-side long before anything renders it, so
without a Python implementation firing at parse, referential validation simply would not
happen on the stack that generates specs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aakar.scenespec import parse_scene_spec, validate_referential

REPO_ROOT = Path(__file__).resolve().parents[3]
DIR = REPO_ROOT / "packages/scenespec/fixtures/referential"
GOLDEN = REPO_ROOT / "specs/golden"
FILES = sorted(DIR.glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_fixtures_exist_on_both_sides_of_the_line() -> None:
    fixtures = [_load(p) for p in FILES]
    assert len([f for f in fixtures if not f["expect"]]) >= 3
    assert len([f for f in fixtures if f["expect"]]) >= 5


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_referential_errors_match_the_fixture(path: Path) -> None:
    fixture = _load(path)
    actual = [{"code": e.code, "path": e.path} for e in validate_referential(fixture["spec"])]
    assert actual == fixture["expect"], fixture["note"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_the_same_verdict_arrives_through_parse(path: Path) -> None:
    """Firing at parse is the whole ruling — a broken spec must not need a render."""
    fixture = _load(path)
    result = parse_scene_spec(fixture["spec"])
    if not fixture["expect"]:
        assert result.ok, result.errors
        return
    assert not result.ok
    assert [i.code for i in result.issues] == [e["code"] for e in fixture["expect"]]


def test_near_miss_parent_id_is_suggested() -> None:
    fixture = _load(DIR / "parent-not-found-near-miss.json")
    errors = validate_referential(fixture["spec"])
    assert 'did you mean "eyeball"?' in errors[0].message


def test_unrelated_id_is_not_suggested() -> None:
    spec = {"parts": [{"id": "eyeball"}, {"id": "lens", "parent_id": "mitochondrion"}]}
    assert "did you mean" not in validate_referential(spec)[0].message


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.stem)
def test_golden_specs_are_referentially_valid(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert validate_referential(document) == []
    assert parse_scene_spec(document).ok


def test_schema_failure_short_circuits_before_referential_checks() -> None:
    """Referential checks need `parts` to be the right shape before they mean anything."""
    result = parse_scene_spec({"schema_version": "1.1", "topic": "x", "title": "X", "parts": []})
    assert not result.ok
    assert all(i.code.startswith("schema:") for i in result.issues)
