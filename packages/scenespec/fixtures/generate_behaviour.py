"""Generate the behavioural corpus: inputs plus their schema-derived expected form.

The verdict corpus asks "do both validators accept or reject the same documents". This
one asks the harder question: "do both validators produce the same *values*". D-018 is
the case in point — zod applied no geometry defaults while pydantic applied them all, and
the verdict corpus could not see it because both said "valid".

Expected forms are computed from **the schema**, not from either parser. Generating them
from one stack would make that stack's bug the expected answer.

Every "present" fixture uses a NON-default value, so a parser that wrongly overrides a
supplied value with the default fails rather than coincidentally matching.

Run:  cd services/api && uv run python ../../packages/scenespec/fixtures/generate_behaviour.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
SCHEMA: dict[str, Any] = json.loads(
    (PACKAGE / "scenespec.schema.json").read_text(encoding="utf-8")
)

_spec = importlib.util.spec_from_file_location("scenespec_canonical", PACKAGE / "canonical.py")
assert _spec is not None and _spec.loader is not None
canonical_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canonical_mod)

INPUT_DIR = HERE / "behaviour" / "input"
EXPECTED_DIR = HERE / "behaviour" / "expected"

SCHEMA_VERSION = SCHEMA["properties"]["schema_version"]["const"]

# Geometry with every defaulted field OMITTED, and the same with a NON-default value.
GEOMETRY_ABSENT: dict[str, dict[str, Any]] = {
    "sphere": {"type": "sphere", "radius": 1},
    "box": {"type": "box", "w": 1, "h": 2, "d": 3},
    "cylinder": {"type": "cylinder", "r_top": 1, "r_bottom": 2, "height": 3},
    "cone": {"type": "cone", "radius": 1, "height": 2},
    "torus": {"type": "torus", "radius": 2, "tube": 0.5},
    "capsule": {"type": "capsule", "radius": 0.5, "length": 2},
    "tube": {"type": "tube", "path": [[0, 0, 0], [1, 1, 1]], "radius": 0.2},
    "lathe": {"type": "lathe", "profile": [[0, 0], [1, 0], [0, 1]]},
    "extrude": {"type": "extrude", "shape": [[0, 0], [1, 0], [1, 1]], "depth": 0.5},
}

GEOMETRY_PRESENT: dict[str, dict[str, Any]] = {
    **{k: deepcopy(v) for k, v in GEOMETRY_ABSENT.items()},
    "cylinder": {"type": "cylinder", "r_top": 1, "r_bottom": 2, "height": 3, "open_ended": True},
    "tube": {"type": "tube", "path": [[0, 0, 0], [1, 1, 1]], "radius": 0.2, "closed": True},
    "lathe": {"type": "lathe", "profile": [[0, 0], [1, 0], [0, 1]], "segments": 64},
}


def spec_with(part_extra: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    part: dict[str, Any] = {
        "id": "p",
        "name": "Part",
        "geometry": deepcopy(geometry),
        "material": {"color": "#aabbcc"},
        "provenance": {"chunk_ids": ["golden"]},
    }
    part.update(deepcopy(part_extra))
    return {
        "schema_version": SCHEMA_VERSION,
        "topic": "behaviour",
        "title": "Behaviour fixture",
        "parts": [part],
    }


def cases() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    # Every geometry variant, defaults absent and defaults supplied.
    for name, geometry in GEOMETRY_ABSENT.items():
        out[f"geometry-{name}-defaults-absent"] = spec_with({}, geometry)
    for name, geometry in GEOMETRY_PRESENT.items():
        out[f"geometry-{name}-defaults-present"] = spec_with({}, geometry)

    # One pair per defaulted field, using a non-default value when present.
    out["field-open_ended-absent"] = spec_with({}, GEOMETRY_ABSENT["cylinder"])
    out["field-open_ended-present"] = spec_with({}, GEOMETRY_PRESENT["cylinder"])

    out["field-closed-absent"] = spec_with({}, GEOMETRY_ABSENT["tube"])
    out["field-closed-present"] = spec_with({}, GEOMETRY_PRESENT["tube"])

    out["field-segments-absent"] = spec_with({}, GEOMETRY_ABSENT["lathe"])
    out["field-segments-present"] = spec_with({}, GEOMETRY_PRESENT["lathe"])

    out["field-opacity-absent"] = spec_with({}, GEOMETRY_ABSENT["sphere"])
    present = spec_with({}, GEOMETRY_ABSENT["sphere"])
    present["parts"][0]["material"] = {"color": "#aabbcc", "opacity": 0.25}
    out["field-opacity-present"] = present

    out["field-roughness-absent"] = spec_with({}, GEOMETRY_ABSENT["sphere"])
    present = spec_with({}, GEOMETRY_ABSENT["sphere"])
    present["parts"][0]["material"] = {"color": "#aabbcc", "roughness": 0.9}
    out["field-roughness-present"] = present

    out["field-clip_exempt-absent"] = spec_with({}, GEOMETRY_ABSENT["sphere"])
    out["field-clip_exempt-present"] = spec_with({"clip_exempt": True}, GEOMETRY_ABSENT["sphere"])

    out["field-importance-absent"] = spec_with({}, GEOMETRY_ABSENT["sphere"])
    out["field-importance-present"] = spec_with(
        {"importance": "secondary"}, GEOMETRY_ABSENT["sphere"]
    )

    # Every optional non-defaulted field absent, then present, so "omitted" and
    # "supplied" are both exercised for the whole Part shape.
    out["optionals-all-absent"] = spec_with({}, GEOMETRY_ABSENT["sphere"])
    out["optionals-all-present"] = {
        "schema_version": SCHEMA_VERSION,
        "topic": "behaviour",
        "title": "Behaviour fixture",
        "parts": [
            {
                "id": "root",
                "name": "Root",
                "aliases": ["alpha", "beta"],
                "instance_of": "Root Concept",
                "geometry": GEOMETRY_PRESENT["lathe"],
                "transform": {
                    "position": [1, -2, 3.5],
                    "rotation": [90, -45, 0],
                    "scale": [1, 2, 0.5],
                },
                "material": {"color": "#FFAA00", "opacity": 0.25, "roughness": 0.9},
                "clip_exempt": True,
                "importance": "secondary",
                "provenance": {"chunk_ids": ["c1", "c2"], "evidence": "quoted text"},
            },
            {
                "id": "child",
                "name": "Child",
                "parent_id": "root",
                "geometry": GEOMETRY_ABSENT["sphere"],
                "material": {"color": "#001122"},
                "provenance": {"chunk_ids": ["c3"]},
            },
        ],
        "cutaway": {"enabled": True, "plane": {"normal": [0, 0, -1], "constant": 0.25}},
        "camera_hint": {"position": [3, 2, 4], "look_at": [0, 0, 0]},
    }

    return out


def main() -> int:
    for directory in (INPUT_DIR, EXPECTED_DIR):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

    built = cases()
    for name, document in sorted(built.items()):
        (INPUT_DIR / f"{name}.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        filled = canonical_mod.apply_defaults(deepcopy(document), SCHEMA, SCHEMA)
        (EXPECTED_DIR / f"{name}.json").write_text(
            canonical_mod.dumps(filled), encoding="utf-8"
        )

    print(f"behavioural fixtures written : {len(built)}")
    print(f"  inputs   -> {INPUT_DIR.relative_to(PACKAGE.parent.parent)}")
    print(f"  expected -> {EXPECTED_DIR.relative_to(PACKAGE.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
