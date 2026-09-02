"""The verified structure label set (3A gate) and its scope limits.

`evals/golden-structures/structures.json` is the ground truth the extractor is measured
against. It carries its own rules (D-064), its scope limits, and a certification block; this
module loads all three so the runner can print them beside every number rather than leave
them in a file nobody reopens.

The label-set commit is **derived from git at load time**, never read from the file. A
commit cannot contain its own hash, and a stale hand-typed value would certify numbers
against the wrong labels (D-065).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .verify import find_collisions

#: `services/api/aakar/structures/labels.py` -> repo root -> `evals/golden-structures`.
LABELS_PATH = (
    Path(__file__).resolve().parents[4] / "evals" / "golden-structures" / "structures.json"
)


@dataclass(frozen=True)
class LabelledEntity:
    name: str
    kind: str
    modellable: bool
    surface_forms: tuple[str, ...]
    naming_chunks: tuple[str, ...]
    pages: tuple[str, ...]

    @property
    def all_forms(self) -> tuple[str, ...]:
        return (self.name, *self.surface_forms)


@dataclass(frozen=True)
class LabelRules:
    category_nouns: frozenset[str]
    naming_constructions: tuple[str, ...]


@dataclass(frozen=True)
class StructureLabels:
    entities: tuple[LabelledEntity, ...]
    excluded: tuple[str, ...]
    rules: LabelRules
    verified: bool
    verified_by: str | None
    verified_on: str | None
    scope_limits: dict[str, str]
    #: Method caveats the runner prints on every run (D-068): fit-to-test, open findings.
    method_caveats: dict[str, str]
    certification: dict[str, str | None]
    path: Path

    @property
    def provisional(self) -> bool:
        return not self.verified

    @property
    def modellable(self) -> tuple[LabelledEntity, ...]:
        """The product-relevant subset: 3B's coverage denominator (D-064)."""
        return tuple(e for e in self.entities if e.modellable)

    @property
    def label_set_commit(self) -> str:
        """`git log -1 --format=%h -- <file>`, computed now. Not stored in the file."""
        try:
            out = subprocess.run(  # noqa: S603 - fixed argv
                ["git", "log", "-1", "--format=%h", "--", str(self.path)],
                capture_output=True,
                text=True,
                check=False,
                cwd=self.path.parent,
            )
            return out.stdout.strip() or "uncommitted"
        except OSError:
            return "git unavailable"

    def by_name(self, name: str) -> LabelledEntity:
        for entity in self.entities:
            if entity.name == name:
                return entity
        raise KeyError(name)


def load_labels(path: Path | None = None) -> StructureLabels:
    """Load and sanity-check the label set.

    Refuses a set that claims verification with nobody named (same rule as the provenance
    golden set, D-048) and refuses a set that violates its own R3: a label set with two
    entities claiming one surface form cannot score an extractor for the same defect.
    """
    path = path or LABELS_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))

    verified = bool(raw.get("verified", False))
    verified_by = raw.get("verified_by")
    if verified and not verified_by:
        raise ValueError(
            f"{path.name} sets verified: true but verified_by is empty. A label set with no "
            "one accountable for its labels is not verified."
        )

    entities = tuple(
        LabelledEntity(
            name=str(e["name"]),
            kind=str(e["kind"]),
            modellable=bool(e["modellable"]),
            surface_forms=tuple(str(f) for f in e.get("surface_forms", ())),
            naming_chunks=tuple(str(c) for c in e.get("naming_chunks", ())),
            pages=tuple(str(p) for p in e.get("pages", ())),
        )
        for e in raw["entities"]
    )

    collisions = find_collisions({e.name: e.all_forms for e in entities})
    if collisions:
        listed = "; ".join(f"{c.form!r} claimed by {', '.join(c.entities)}" for c in collisions)
        raise ValueError(f"{path.name} violates its own R3: {listed}")

    rules_raw = raw.get("label_rules", {})
    rules = LabelRules(
        category_nouns=frozenset(str(n).lower() for n in rules_raw.get("CATEGORY_NOUNS", ())),
        naming_constructions=tuple(str(n) for n in rules_raw.get("NAMING_CONSTRUCTIONS", ())),
    )

    return StructureLabels(
        entities=entities,
        excluded=tuple(str(x["candidate"]) for x in raw.get("excluded_candidates", ())),
        rules=rules,
        verified=verified,
        verified_by=verified_by,
        verified_on=raw.get("verified_on"),
        scope_limits={str(k): str(v) for k, v in raw.get("SCOPE_LIMITS", {}).items()},
        method_caveats={str(k): str(v) for k, v in raw.get("method_caveats", {}).items()},
        certification={str(k): v for k, v in raw.get("certification", {}).items()},
        path=path,
    )
