"""Generated spec against the hand-written golden (3B gate).

Not an exact-match test — many valid specs exist for one topic. Three things are reported,
as the gate asks, and nothing is scored:

* **structures present in the golden and absent in the generated, and vice versa** —
  matched on names and aliases with the deterministic inflector applied to both sides, so
  *vitreous humour* and *vitreous humor* are one structure;
* **depth and parent-graph shape** — roots, maximum depth, and how many parts carry a
  parent, because D-031 says a parent is attachment and a generator that nests everything
  has misread it;
* **geometry type distribution** — the nine types, counted on each side.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aakar.structures import inflections, normalise


@dataclass(frozen=True)
class GraphShape:
    parts: int
    roots: int
    max_depth: int
    with_parent: int


@dataclass(frozen=True)
class Comparison:
    only_in_golden: tuple[str, ...]
    only_in_generated: tuple[str, ...]
    matched: tuple[tuple[str, str], ...]
    golden_shape: GraphShape
    generated_shape: GraphShape
    golden_geometry: dict[str, int]
    generated_geometry: dict[str, int]


def _forms(part: Mapping[str, Any]) -> set[str]:
    names = [str(part.get("name", ""))] + [str(a) for a in part.get("aliases", []) or []]
    out: set[str] = set()
    for n in names:
        if n:
            out.add(normalise(n))
            out |= {normalise(f) for f in inflections(n)}
    return out


def shape(spec: Mapping[str, Any]) -> GraphShape:
    parts = [p for p in spec.get("parts", []) if isinstance(p, dict)]
    parent = {str(p.get("id")): p.get("parent_id") for p in parts}

    def depth(pid: str) -> int:
        d, seen = 0, set()
        while parent.get(pid) and pid not in seen:
            seen.add(pid)
            pid = str(parent[pid])
            d += 1
        return d

    return GraphShape(
        parts=len(parts),
        roots=sum(1 for p in parts if not p.get("parent_id")),
        max_depth=max((depth(str(p.get("id"))) for p in parts), default=0),
        with_parent=sum(1 for p in parts if p.get("parent_id")),
    )


def geometry(spec: Mapping[str, Any]) -> dict[str, int]:
    return dict(
        Counter(
            str((p.get("geometry") or {}).get("type", "?"))
            for p in spec.get("parts", [])
            if isinstance(p, dict)
        )
    )


def compare_to_golden(generated: Mapping[str, Any], golden: Mapping[str, Any]) -> Comparison:
    gen_parts = [p for p in generated.get("parts", []) if isinstance(p, dict)]
    gold_parts = [p for p in golden.get("parts", []) if isinstance(p, dict)]
    gen_forms = {str(p.get("id")): _forms(p) for p in gen_parts}
    taken: set[str] = set()
    matched: list[tuple[str, str]] = []
    only_gold: list[str] = []
    for g in gold_parts:
        gf = _forms(g)
        hit = next((gid for gid, f in gen_forms.items() if gid not in taken and f & gf), None)
        if hit is None:
            only_gold.append(str(g.get("name")))
        else:
            taken.add(hit)
            matched.append((str(g.get("name")), hit))
    only_gen = [str(p.get("name")) for p in gen_parts if str(p.get("id")) not in taken]
    return Comparison(
        only_in_golden=tuple(only_gold),
        only_in_generated=tuple(only_gen),
        matched=tuple(matched),
        golden_shape=shape(golden),
        generated_shape=shape(generated),
        golden_geometry=geometry(golden),
        generated_geometry=geometry(generated),
    )
