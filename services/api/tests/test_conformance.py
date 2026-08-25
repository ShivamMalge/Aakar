"""Cross-validator conformance corpus — pydantic side.

`codegen-check` compares generated **bytes**. A generator that regenerates faithfully but
emits a validator which accepts everything passes the drift test while validating
nothing; that is exactly what D-015 was, and it was caught by reading the generated file
rather than by any test.

Every fixture here is also run through the zod validator by
`apps/web/src/scenespec/conformance.test.ts`. Each fixture declares the outcome it
expects, so if the two stacks ever diverge, whichever one is wrong fails its own suite.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aakar.scenespec.generated import SceneSpec

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "packages/scenespec/fixtures"
VALID_DIR = FIXTURES / "valid"
INVALID_DIR = FIXTURES / "invalid"

VALID_FILES = sorted(VALID_DIR.glob("*.json"))
INVALID_FILES = sorted(INVALID_DIR.glob("*.json"))


def _load_generator() -> Any:
    """The constraint enumerator lives with the fixtures so there is one source of truth.

    Importing it here rather than re-implementing the walk is the whole point: if the
    enumeration and the corpus could drift apart, the coverage test below would be
    checking a hand-kept list against itself.
    """
    spec = importlib.util.spec_from_file_location("scenespec_fixture_gen", FIXTURES / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_generator()


def _fixture(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_the_corpus_exists() -> None:
    assert len(VALID_FILES) >= 5, "spec asks for at least five accepted SceneSpecs"
    assert len(INVALID_FILES) >= 50, "the invalid corpus looks truncated"


@pytest.mark.parametrize("path", VALID_FILES, ids=lambda p: p.stem)
def test_valid_fixture_is_accepted(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    SceneSpec.model_validate(document)


@pytest.mark.parametrize("path", INVALID_FILES, ids=lambda p: p.stem)
def test_invalid_fixture_is_rejected(path: Path) -> None:
    fixture = _fixture(path)
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(fixture["spec"])


@pytest.mark.parametrize("path", INVALID_FILES, ids=lambda p: p.stem)
def test_invalid_fixture_names_the_constraint_it_violates(path: Path) -> None:
    fixture = _fixture(path)
    for field in ("violates", "pointer", "target", "note", "spec"):
        assert field in fixture, f"{path.name} is missing {field!r}"
    assert fixture["violates"], f"{path.name} does not name a constraint"


def test_every_schema_constraint_has_a_fixture() -> None:
    """The enumeration comes from the schema, not from a list somebody maintains.

    Adding a constraint to scenespec.schema.json without adding a fixture fails here —
    which is what stops the corpus quietly falling behind the schema it is meant to pin.
    """
    enumerated = GENERATOR.enumerate_constraints(GENERATOR.SCHEMA)
    covered = {f"{_fixture(p)['pointer']} {_fixture(p)['violates']}" for p in INVALID_FILES}
    missing = sorted(set(enumerated) - covered)
    assert not missing, "schema constraints with no fixture:\n  " + "\n  ".join(missing)


def test_a_vacuous_validator_would_fail_this_corpus() -> None:
    """Guards the guard.

    If every fixture were accepted — the D-015 failure mode — the rejection tests above
    would fail. This states the inverse explicitly so the corpus cannot be silently
    reduced to a set of documents that are all valid anyway.
    """
    accepted = 0
    for path in INVALID_FILES:
        try:
            SceneSpec.model_validate(_fixture(path)["spec"])
            accepted += 1
        except ValidationError:
            pass
    assert accepted == 0, f"{accepted} invalid fixtures were accepted by pydantic"
