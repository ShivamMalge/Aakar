"""Behavioural conformance — pydantic side.

Verdict agreement is not behavioural agreement. Both generated validators can accept the
same document and hand back different *values*: before D-018, zod applied no geometry
defaults while pydantic applied them all, so a lathe with no `segments` reached the web
compiler as `undefined` and this stack as `32`. The verdict corpus could not see it —
both stacks said "valid".

Each fixture is parsed, canonicalised, and deep-compared against an expected form
computed from **the schema**. Neither parser defines the truth; if the expected form came
from one stack, that stack's bug would become the expected answer.

The zod mirror is apps/web/src/scenespec/behaviour.test.ts, over the same files.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from aakar.scenespec import parse_scene_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "packages/scenespec"
INPUT_DIR = PACKAGE / "fixtures/behaviour/input"
EXPECTED_DIR = PACKAGE / "fixtures/behaviour/expected"

SCHEMA: dict[str, Any] = json.loads((PACKAGE / "scenespec.schema.json").read_text(encoding="utf-8"))
INPUTS = sorted(INPUT_DIR.glob("*.json"))


def _load_canonical() -> Any:
    spec = importlib.util.spec_from_file_location("scenespec_canonical", PACKAGE / "canonical.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CANONICAL = _load_canonical()


def test_the_behavioural_corpus_exists() -> None:
    assert len(INPUTS) >= 20, "behavioural corpus looks truncated"
    assert len(list(EXPECTED_DIR.glob("*.json"))) == len(INPUTS)


def _differences(expected: Any, actual: Any, where: str = "") -> list[str]:
    """Name the field and both values — "not equal" is not a usable failure here."""
    out: list[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            path = f"{where}.{key}" if where else key
            if key not in actual:
                out.append(f"  {path}: expected {expected[key]!r}, missing from output")
            elif key not in expected:
                out.append(f"  {path}: unexpected {actual[key]!r} in output")
            else:
                out.extend(_differences(expected[key], actual[key], path))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(f"  {where}: expected {len(expected)} items, got {len(actual)}")
        else:
            for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
                out.extend(_differences(e, a, f"{where}[{i}]"))
    elif expected != actual:
        out.append(f"  {where}: expected {expected!r}, got {actual!r}")
    return out


@pytest.mark.parametrize("path", INPUTS, ids=lambda p: p.stem)
def test_parsed_output_matches_the_schema_derived_expectation(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    result = parse_scene_spec(document)
    assert result.ok, result.errors
    assert result.spec is not None

    actual = CANONICAL.canonical(result.spec.model_dump(mode="json"))
    expected = json.loads((EXPECTED_DIR / path.name).read_text(encoding="utf-8"))

    if actual != expected:
        raise AssertionError(
            f"{path.name}: pydantic output differs from the schema-derived expectation\n"
            + "\n".join(_differences(expected, actual))
        )


def test_every_defaulted_field_has_a_present_and_an_absent_fixture() -> None:
    """The mirror of the verdict corpus's coverage test.

    A defaulted field that is never omitted cannot reveal a defaults divergence, which is
    exactly the shape D-018 had. Adding a `default` to the schema without adding both
    fixtures fails here.
    """
    declared = CANONICAL.defaulted_pointers(SCHEMA)
    present: set[str] = set()
    absent: set[str] = set()

    for path in INPUTS:
        document = json.loads(path.read_text(encoding="utf-8"))
        for pointer, state in CANONICAL.observe_defaults(document, SCHEMA, SCHEMA).items():
            (present if state == "present" else absent).add(pointer)

    missing_present = sorted(declared - present)
    missing_absent = sorted(declared - absent)
    assert not missing_present, f"defaulted fields never supplied: {missing_present}"
    assert not missing_absent, f"defaulted fields never omitted: {missing_absent}"


def test_every_geometry_variant_is_covered() -> None:
    covered: set[str] = set()
    for path in INPUTS:
        document = json.loads(path.read_text(encoding="utf-8"))
        for part in document["parts"]:
            covered.add(str(part["geometry"]["type"]))
    expected = {
        str(branch["$ref"]).split("/")[-1].lower()
        for branch in SCHEMA["$defs"]["Geometry"]["oneOf"]
    }
    assert covered == expected, f"geometry variants not exercised: {sorted(expected - covered)}"
