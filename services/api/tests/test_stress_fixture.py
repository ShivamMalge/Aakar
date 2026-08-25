"""Stress fixture — pydantic side (Phase 1 review, item 5).

The largest golden spec is 13 parts at depth 4; the schema permits 40. Phase 3 generates
against that cap routinely, so it needs exercising before rather than after.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from aakar.scenespec import parse_scene_spec, validate_referential

REPO_ROOT = Path(__file__).resolve().parents[3]
STRESS = REPO_ROOT / "specs/stress/neuron.json"


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(STRESS.read_text(encoding="utf-8"))
    return loaded


def _depth(document: dict[str, Any]) -> int:
    parent_of = {p["id"]: p.get("parent_id") for p in document["parts"]}
    deepest = 0
    for part_id in parent_of:
        depth, node = 0, parent_of[part_id]
        while node is not None:
            depth += 1
            node = parent_of.get(node)
        deepest = max(deepest, depth)
    return deepest


def test_it_sits_exactly_on_the_part_cap(document: dict[str, Any]) -> None:
    assert len(document["parts"]) == 40


def test_it_nests_at_least_six_deep(document: dict[str, Any]) -> None:
    assert _depth(document) >= 6


def test_it_exercises_every_geometry_type(document: dict[str, Any]) -> None:
    assert len({p["geometry"]["type"] for p in document["parts"]}) == 9


def test_it_parses_and_is_referentially_valid(document: dict[str, Any]) -> None:
    result = parse_scene_spec(document)
    assert result.ok, result.errors
    assert validate_referential(document) == []


def test_instance_of_groups_share_a_retrieval_target(document: dict[str, Any]) -> None:
    groups: dict[str, list[str]] = {}
    for part in document["parts"]:
        if "instance_of" in part:
            groups.setdefault(part["instance_of"], []).append(part["id"])
    shared = {k: v for k, v in groups.items() if len(v) > 1}
    assert shared, "no instance_of group with more than one member"
    # Ruling B: sharing instance_of is what lets repeated structures share a name.
    for members in shared.values():
        names = {p["name"] for p in document["parts"] if p["id"] in members}
        assert len(names) == 1


def test_provenance_strength_is_mixed(document: dict[str, Any]) -> None:
    parts = document["parts"]
    assert any("evidence" in p["provenance"] for p in parts)
    assert any("evidence" not in p["provenance"] for p in parts)
    # The schema requires >= 1 chunk id, so "no provenance at all" is not expressible.
    assert all(p["provenance"]["chunk_ids"] for p in parts)


def test_at_least_one_part_is_clip_exempt(document: dict[str, Any]) -> None:
    assert any(p.get("clip_exempt") for p in document["parts"])


def test_parse_timing(document: dict[str, Any]) -> None:
    runs = 20
    start = time.perf_counter()
    for _ in range(runs):
        parse_scene_spec(document)
    per_run_ms = (time.perf_counter() - start) / runs * 1000
    print(f"\n  pydantic parse + referential: {per_run_ms:.2f} ms (mean of {runs})")
    assert per_run_ms < 500
