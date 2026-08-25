"""Tasks 0.3 / 0.4 — the schema is the single source of truth (D7).

These run in the API suite because the pydantic side is generated here; the zod side has
its mirror tests under apps/web/src/scenespec/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aakar.scenespec.generated import SceneSpec

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((REPO_ROOT / "packages/scenespec/scenespec.schema.json").read_text())
EXAMPLE = REPO_ROOT / "packages/scenespec/examples/section4_example.json"


@pytest.fixture
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text())
    return loaded


def test_section4_example_parses(spec: dict[str, Any]) -> None:
    """The example printed in spec §4 must validate against the schema built from it."""
    parsed = SceneSpec.model_validate(spec)
    assert len(parsed.parts) == 2


def test_geometry_vocabulary_is_closed_and_complete() -> None:
    """Spec §4 names nine geometry types. Adding a tenth is a schema change, not a prompt change."""
    variants = SCHEMA["$defs"]["Geometry"]["oneOf"]
    names = {
        SCHEMA["$defs"][ref["$ref"].split("/")[-1]]["properties"]["type"]["const"]
        for ref in variants
    }
    assert names == {
        "sphere",
        "box",
        "cylinder",
        "cone",
        "torus",
        "capsule",
        "tube",
        "lathe",
        "extrude",
    }


def test_part_cap_is_forty(spec: dict[str, Any]) -> None:
    assert SCHEMA["properties"]["parts"]["maxItems"] == 40
    spec["parts"] = [dict(spec["parts"][0], id=f"p{i}") for i in range(41)]
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_provenance_is_mandatory(spec: dict[str, Any]) -> None:
    """Rule 6 — a part with no chunk_ids does not exist as far as the schema is concerned."""
    del spec["parts"][0]["provenance"]
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_empty_chunk_ids_is_rejected(spec: dict[str, Any]) -> None:
    spec["parts"][0]["provenance"]["chunk_ids"] = []
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_lathe_profile_needs_three_points(spec: dict[str, Any]) -> None:
    spec["parts"][1]["geometry"]["profile"] = [[0, -0.4], [0.55, 0]]
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_colors_must_be_hex(spec: dict[str, Any]) -> None:
    spec["parts"][0]["material"]["color"] = "cornflowerblue"
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_unknown_geometry_type_is_rejected(spec: dict[str, Any]) -> None:
    """CSG/booleans are out of scope for v1 — the schema, not a prompt, is what says so."""
    spec["parts"][0]["geometry"] = {"type": "csg_subtract", "a": "x", "b": "y"}
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_extra_fields_are_rejected(spec: dict[str, Any]) -> None:
    """A model inventing a field must fail loudly rather than have it silently dropped."""
    spec["parts"][0]["glow_intensity"] = 3
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_numeric_bounds_hold(spec: dict[str, Any]) -> None:
    spec["parts"][0]["geometry"]["radius"] = 0
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_opacity_is_clamped_to_unit_range(spec: dict[str, Any]) -> None:
    spec["parts"][0]["material"]["opacity"] = 1.4
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_missing_geometry_is_rejected(spec: dict[str, Any]) -> None:
    del spec["parts"][0]["geometry"]
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_geometry_without_a_type_tag_is_rejected(spec: dict[str, Any]) -> None:
    spec["parts"][0]["geometry"] = {"radius": 1}
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec)


def test_geometry_defaults_are_applied(spec: dict[str, Any]) -> None:
    """Mirrors the zod side (D-018) — both stacks must default `segments` to 32."""
    spec["parts"][1]["geometry"] = {"type": "lathe", "profile": [[0, 0], [1, 0], [0, 1]]}
    parsed = SceneSpec.model_validate(spec)
    geometry = parsed.parts[1].geometry.root
    assert getattr(geometry, "segments", None) == 32


def test_golden_sentinel_is_accepted(spec: dict[str, Any]) -> None:
    """D-003: Phase 1 has no corpus, so `golden` is a reserved chunk id until 2.9 backfills."""
    spec["parts"][0]["provenance"]["chunk_ids"] = ["golden"]
    SceneSpec.model_validate(spec)
