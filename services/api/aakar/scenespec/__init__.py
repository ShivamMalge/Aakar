"""SceneSpec parsing for the API.

`generated.py` is produced by `make codegen` and must stay replaceable — import from
this module, never from it directly (D7).

`parse_scene_spec` is the Python parse entry point, and it runs the referential
constraints as well as the schema. Both halves matter server-side: Phase 3's generator
parses and stores a spec long before anything renders it, so referential validation has
to happen here or it does not happen at all on this stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .generated import SceneSpec
from .provenance import (
    PARSE_TIME_STRENGTHS,
    ParseTimeStrength,
    ProvenanceStrength,
    assert_parse_time,
    provenance_strengths,
    strength_counts,
    ungrounded_parts,
)
from .referential import ReferentialCode, ReferentialError, validate_referential

__all__ = [
    "ParseIssue",
    "ParseResult",
    "ParseTimeStrength",
    "ProvenanceStrength",
    "ReferentialCode",
    "ReferentialError",
    "SceneSpec",
    "parse_scene_spec",
    "assert_parse_time",
    "provenance_strengths",
    "strength_counts",
    "ungrounded_parts",
    "validate_referential",
]


@dataclass(frozen=True)
class ParseIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ParseResult:
    spec: SceneSpec | None
    issues: tuple[ParseIssue, ...]
    # Derived, never author-supplied (D-025). Zero-provenance parts are legal as of
    # schema 1.2 and are a curation signal, not an error.
    provenance_strength: dict[str, ParseTimeStrength] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.spec is not None

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(f"{i.path}: {i.message}" if i.path else i.message for i in self.issues)


def parse_scene_spec(document: Any) -> ParseResult:
    """Schema-validate, then referentially validate. Never raises."""
    try:
        spec = SceneSpec.model_validate(document)
    except ValidationError as exc:
        issues = tuple(
            ParseIssue(
                code=f"schema:{error['type']}",
                path=".".join(str(part) for part in error["loc"]),
                message=str(error["msg"]),
            )
            for error in exc.errors()
        )
        return ParseResult(spec=None, issues=issues)

    referential = validate_referential(document)
    if referential:
        return ParseResult(
            spec=None,
            issues=tuple(
                ParseIssue(code=e.code, path=e.path, message=e.message) for e in referential
            ),
        )

    strengths = provenance_strengths(document)

    # D-030: parse may only ever emit `none` or `unverified`. A verified strength here
    # would be fabricated confidence — nothing has read the chunk text yet — so it is a
    # validation error rather than a convention someone can quietly break.
    premature = assert_parse_time(strengths)
    if premature:
        return ParseResult(
            spec=None,
            issues=tuple(
                ParseIssue(
                    code="provenance:premature_strength",
                    path=f"parts.{part_id}.provenance",
                    message=(
                        f"provenance_strength {strength!r} was derived at parse time. Only "
                        f"{PARSE_TIME_STRENGTHS} are knowable without corpus text; weak and "
                        "strong resolve in Phase 2B/3 (D-030)."
                    ),
                )
                for part_id, strength in premature
            ),
        )

    return ParseResult(spec=spec, issues=(), provenance_strength=strengths)
