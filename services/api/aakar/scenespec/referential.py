"""Referential constraints — the shared contract, Python implementation.

The mirror of ``packages/scenespec/referential.ts``. JSON Schema cannot express
referential integrity, so these three live outside the schema:

1. part ids are unique within a spec
2. every ``parent_id`` resolves to a part in the same spec
3. the parent graph is acyclic

Unique *names* and a *single root* are deliberately not enforced — unique ids is the
real invariant, and all three golden specs are legitimately multi-root.

This exists because the TypeScript version fired only inside ``compile()``. Phase 3's
generator parses and stores server-side and never renders until the critic runs, so a
structurally broken spec would have surfaced as a render failure rather than as a
diagnosable validation error — and the repair loop cannot repair what it cannot
diagnose.

The cross-stack contract is the ``(code, path)`` pair, asserted from
``packages/scenespec/fixtures/referential/``. Message text is each stack's own business.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ReferentialCode = Literal[
    "duplicate_part_id",
    "self_parent",
    "parent_not_found",
    "parent_cycle",
]


@dataclass(frozen=True)
class ReferentialError:
    code: ReferentialCode
    path: str
    message: str


def _distance(a: str, b: str) -> int:
    """Levenshtein, used only to suggest a near-miss id."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            current[j] = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + (ca != cb),
            )
        previous = current
    return previous[len(b)]


def nearest(target: str, candidates: Iterable[str]) -> str | None:
    """Only suggest something genuinely close, or the hint is noise."""
    best: str | None = None
    best_score = float("inf")
    for candidate in candidates:
        score = _distance(target, candidate)
        if score < best_score:
            best_score, best = score, candidate
    threshold = max(2, len(target) // 3)
    return best if best is not None and best_score <= threshold else None


def _parts(spec: Any) -> Sequence[Mapping[str, Any]]:
    # Accepts a raw document or a parsed pydantic SceneSpec — the generator validates
    # before constructing a model, the API validates after.
    raw = spec.get("parts") or [] if isinstance(spec, Mapping) else getattr(spec, "parts", []) or []
    out: list[Mapping[str, Any]] = []
    for part in raw:
        if isinstance(part, Mapping):
            out.append(part)
        else:
            out.append(
                {
                    "id": _unwrap(getattr(part, "id", None)),
                    "parent_id": _unwrap(getattr(part, "parent_id", None)),
                }
            )
    return out


def _unwrap(value: Any) -> Any:
    """datamodel-code-generator wraps constrained scalars in RootModel."""
    return getattr(value, "root", value)


def validate_referential(spec: Any) -> list[ReferentialError]:
    """Every referential problem in one pass, not just the first.

    D3 spends at most two repair rounds; a validator reporting one problem per attempt
    burns that budget on bookkeeping rather than on repair.
    """
    errors: list[ReferentialError] = []
    parts = _parts(spec)

    first_index: dict[str, int] = {}
    for i, part in enumerate(parts):
        part_id = str(_unwrap(part.get("id")))
        if part_id in first_index:
            errors.append(
                ReferentialError(
                    code="duplicate_part_id",
                    path=f"parts.{i}.id",
                    message=(
                        f'duplicate part id "{part_id}" — ids must be unique '
                        f"(first used at parts.{first_index[part_id]})"
                    ),
                )
            )
            continue
        first_index[part_id] = i

    ids = list(first_index)

    for i, part in enumerate(parts):
        raw_parent = _unwrap(part.get("parent_id"))
        if raw_parent is None:
            continue
        parent = str(raw_parent)
        part_id = str(_unwrap(part.get("id")))

        if parent == part_id:
            errors.append(
                ReferentialError(
                    code="self_parent",
                    path=f"parts.{i}.parent_id",
                    message=(f'part "{part_id}" is its own parent — a part cannot contain itself'),
                )
            )
            continue

        if parent not in first_index:
            hint = nearest(parent, ids)
            suffix = f' — did you mean "{hint}"?' if hint is not None else ""
            errors.append(
                ReferentialError(
                    code="parent_not_found",
                    path=f"parts.{i}.parent_id",
                    message=(
                        f'part "{part_id}" references parent "{parent}", '
                        f"which is not a part in this spec{suffix}"
                    ),
                )
            )

    errors.extend(_find_cycles(parts, first_index))
    return errors


def _find_cycles(
    parts: Sequence[Mapping[str, Any]], index_by_id: Mapping[str, int]
) -> list[ReferentialError]:
    """Iterative colour-marking walk; reports the cycle it actually traversed."""
    parent_of: dict[str, str] = {}
    for part in parts:
        part_id = str(_unwrap(part.get("id")))
        raw_parent = _unwrap(part.get("parent_id"))
        if raw_parent is None:
            continue
        parent = str(raw_parent)
        # Only edges that resolve — unresolved parents are already reported. Self edges
        # are skipped too: `self_parent` already names that problem precisely, and
        # reporting it again as a length-one cycle gives the repair prompt the same
        # defect twice under two different codes.
        if parent != part_id and parent in index_by_id and part_id not in parent_of:
            parent_of[part_id] = parent

    errors: list[ReferentialError] = []
    state: dict[str, str] = {}
    reported: set[str] = set()

    for start in parent_of:
        if state.get(start) == "done":
            continue

        stack: list[str] = []
        on_stack: set[str] = set()
        node: str | None = start

        while node is not None and state.get(node) != "done":
            if node in on_stack:
                cycle = stack[stack.index(node) :] + [node]
                key = " ".join(sorted(cycle))
                if key not in reported:
                    reported.add(key)
                    errors.append(
                        ReferentialError(
                            code="parent_cycle",
                            path=f"parts.{index_by_id.get(node, 0)}.parent_id",
                            message=(
                                f"parent cycle: {' -> '.join(cycle)} — "
                                "the parent graph must be a tree"
                            ),
                        )
                    )
                break
            stack.append(node)
            on_stack.add(node)
            state[node] = "visiting"
            node = parent_of.get(node)

        for seen in stack:
            state[seen] = "done"

    return errors
