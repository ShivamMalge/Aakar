"""Generate the invalid half of the conformance corpus from the schema itself.

`codegen-check` compares generated **bytes**, so a generator that faithfully emits a
validator which accepts everything still passes the drift test — that is exactly what
D-015 was, and it was caught by reading the output rather than by a test. The corpus
closes that hole, and it is derived by walking `scenespec.schema.json` and violating each
constraint the schema declares, rather than from a hand-kept list that would drift.

Run:  cd services/api && uv run python ../../packages/scenespec/fixtures/generate.py
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE.parent / "scenespec.schema.json"
INVALID_DIR = HERE / "invalid"
HANDWRITTEN_PREFIX = "handwritten-"

SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
DEFS: dict[str, Any] = SCHEMA["$defs"]

# Keywords that constrain a value. `$ref`/`oneOf`/`description`/`default` do not;
# `additionalProperties` counts only when it is `false`.
CONSTRAINT_KEYWORDS = (
    "required",
    "additionalProperties",
    "const",
    "enum",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "minItems",
    "maxItems",
    "type",
    # Not used by the schema today. Listed anyway: if one is ever added, the coverage
    # test fails until a fixture exists, rather than the corpus silently not covering it.
    "exclusiveMaximum",
    "multipleOf",
    "uniqueItems",
)

GEOMETRY_DEFS = (
    "Sphere",
    "Box",
    "Cylinder",
    "Cone",
    "Torus",
    "Capsule",
    "Tube",
    "Lathe",
    "Extrude",
)

GEOMETRY_SAMPLES: dict[str, dict[str, Any]] = {
    "Sphere": {"type": "sphere", "radius": 1.0},
    "Box": {"type": "box", "w": 1.0, "h": 1.0, "d": 1.0},
    "Cylinder": {
        "type": "cylinder",
        "r_top": 1.0,
        "r_bottom": 1.0,
        "height": 2.0,
        "open_ended": False,
    },
    "Cone": {"type": "cone", "radius": 1.0, "height": 2.0},
    "Torus": {"type": "torus", "radius": 2.0, "tube": 0.5},
    "Capsule": {"type": "capsule", "radius": 0.5, "length": 2.0},
    "Tube": {"type": "tube", "path": [[0, 0, 0], [1, 1, 1]], "radius": 0.2, "closed": False},
    "Lathe": {"type": "lathe", "profile": [[0, 0], [1, 0], [0, 1]], "segments": 32},
    "Extrude": {"type": "extrude", "shape": [[0, 0], [1, 0], [1, 1]], "depth": 0.5},
}


class _Delete:
    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<delete>"


DELETE = _Delete()


def base_spec(geometry: str = "Sphere") -> dict[str, Any]:
    """The smallest valid spec that exercises `geometry`. Kept minimal so each fixture
    reads as one violation rather than a wall of unrelated JSON."""
    return {
        "schema_version": "1.2",
        "topic": "conformance",
        "title": "Conformance fixture",
        "parts": [
            {
                "id": "only_part",
                "name": "Only Part",
                "aliases": ["sole part"],
                "instance_of": "Sole Part",
                "geometry": deepcopy(GEOMETRY_SAMPLES[geometry]),
                "transform": {
                    "position": [0, 0, 0],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                },
                "material": {"color": "#aabbcc", "opacity": 1, "roughness": 0.5},
                "clip_exempt": False,
                "importance": "core",
                "provenance": {"chunk_ids": ["golden"], "evidence": "quoted from the chunk"},
            }
        ],
        "cutaway": {"enabled": True, "plane": {"normal": [0, 0, 1], "constant": 0}},
        "camera_hint": {"position": [3, 2, 4], "look_at": [0, 0, 0]},
    }


# Where each $def lives inside `base_spec`. Shared defs get one representative site.
DEF_PATHS: dict[str, str] = {
    "Part": "parts.0",
    "Transform": "parts.0.transform",
    "Material": "parts.0.material",
    "Provenance": "parts.0.provenance",
    "Cutaway": "cutaway",
    "CameraHint": "camera_hint",
    "Geometry": "parts.0.geometry",
    "Vec3": "parts.0.transform.position",
    "Vec2": "parts.0.geometry.profile.0",
    "PartId": "parts.0.id",
    "HexColor": "parts.0.material.color",
    **{name: "parts.0.geometry" for name in GEOMETRY_DEFS},
}

# Which geometry the base needs for a def's site to exist at all.
DEF_GEOMETRY: dict[str, str] = {"Vec2": "Lathe", **{name: name for name in GEOMETRY_DEFS}}


# Maps whose *keys* are names, not keywords. Geometry branches each declare a property
# literally called "type", so scanning these for keywords finds a `type` constraint that
# does not exist.
NAME_MAPS = {"properties", "$defs"}


def enumerate_constraints(
    node: Any, pointer: str = "#", *, is_schema: bool = True
) -> dict[str, dict[str, Any]]:
    """Walk the schema; return {f'{pointer} {keyword}': {...}} for every constraint."""
    found: dict[str, dict[str, Any]] = {}
    if isinstance(node, list):
        for i, item in enumerate(node):
            found.update(enumerate_constraints(item, f"{pointer}/{i}"))
        return found
    if not isinstance(node, dict):
        return found

    if is_schema:
        for keyword in CONSTRAINT_KEYWORDS:
            if keyword not in node:
                continue
            value = node[keyword]
            if keyword == "additionalProperties" and value is not False:
                continue
            found[f"{pointer} {keyword}"] = {
                "pointer": pointer,
                "keyword": keyword,
                "value": value,
            }

    for key, child in node.items():
        if key in {"description", "title", "$id", "$schema", "default"}:
            continue
        found.update(
            enumerate_constraints(child, f"{pointer}/{key}", is_schema=key not in NAME_MAPS)
        )
    return found


def pointer_to_site(pointer: str) -> tuple[str, str] | None:
    """Map a schema pointer to (geometry_needed, document_path), or None if unmapped."""
    parts = pointer.lstrip("#").strip("/").split("/") if pointer != "#" else []

    if not parts:
        return ("Sphere", "")

    if parts[0] == "properties":
        path = "" if len(parts) < 2 else parts[1]
        rest = parts[2:]
        geometry = "Sphere"
    elif parts[0] == "$defs":
        name = parts[1]
        if name not in DEF_PATHS:
            return None
        path = DEF_PATHS[name]
        rest = parts[2:]
        geometry = DEF_GEOMETRY.get(name, "Sphere")
    else:
        return None

    for i, token in enumerate(rest):
        if token == "properties":
            continue
        if token == "items":
            path = f"{path}.0" if path else "0"
            continue
        if token in {"oneOf"}:
            return None
        # A property name, unless it is the index that follows `oneOf`.
        if i > 0 and rest[i - 1] == "properties":
            path = f"{path}.{token}" if path else token
        elif rest[i - 1] == "items" if i > 0 else False:
            return None
        else:
            path = f"{path}.{token}" if path else token

    return (geometry, path)


def get_path(document: Any, path: str) -> Any:
    if path == "":
        return document
    node = document
    for key in path.split("."):
        node = node[int(key)] if key.isdigit() else node[key]
    return node


def set_path(document: Any, path: str, value: Any) -> Any:
    if path == "":
        return value
    keys: list[Any] = [int(k) if k.isdigit() else k for k in path.split(".")]
    node = document
    for key in keys[:-1]:
        node = node[key]
    if value is DELETE:
        del node[keys[-1]]
    else:
        node[keys[-1]] = value
    return document


WRONG_FOR_TYPE: dict[str, Any] = {
    "object": "not-an-object",
    "array": "not-an-array",
    "string": 12345,
    "number": "not-a-number",
    "integer": 1.5,
    "boolean": "not-a-boolean",
}


def violations(constraint: dict[str, Any], path: str) -> list[tuple[str, Any, str]]:
    """Return [(target_path, violating_value, note)] for one constraint."""
    keyword = constraint["keyword"]
    value = constraint["value"]

    if keyword == "required":
        return [
            (f"{path}.{field}" if path else field, DELETE, f"required field {field!r} removed")
            for field in value
        ]
    if keyword == "additionalProperties":
        key = "not_a_real_field"
        return [(f"{path}.{key}" if path else key, 1, "undeclared property added")]
    if keyword == "const":
        return [(path, f"not-{value}", f"must be the constant {value!r}")]
    if keyword == "enum":
        return [(path, "not-a-member", f"must be one of {value}")]
    if keyword == "pattern":
        return [(path, "!! invalid !!", f"must match {value}")]
    if keyword == "minLength":
        return [(path, "", f"shorter than minLength {value}")]
    if keyword == "maxLength":
        return [(path, "x" * (int(value) + 1), f"longer than maxLength {value}")]
    if keyword == "minimum":
        return [(path, value - 1, f"below minimum {value}")]
    if keyword == "maximum":
        return [(path, value + 1, f"above maximum {value}")]
    if keyword == "exclusiveMinimum":
        return [(path, value, f"equal to exclusiveMinimum {value}, which is excluded")]
    if keyword == "exclusiveMaximum":
        return [(path, value, f"equal to exclusiveMaximum {value}, which is excluded")]
    if keyword == "multipleOf":
        return [(path, value / 2, f"not a multiple of {value}")]
    if keyword == "uniqueItems":
        return []  # handled with the array keywords, which need a live element to clone
    if keyword == "type":
        wrong = WRONG_FOR_TYPE.get(value if isinstance(value, str) else "")
        if wrong is None:
            return []
        return [(path, wrong, f"wrong JSON type, expected {value}")]
    return []


def array_violation(
    constraint: dict[str, Any], path: str, spec: dict[str, Any]
) -> tuple[str, Any, str] | None:
    """minItems/maxItems need a valid element to clone, so they are handled apart."""
    keyword = constraint["keyword"]
    count = int(constraint["value"])
    try:
        current = get_path(spec, path)
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(current, list) or not current:
        return None

    if keyword == "minItems":
        return (path, current[: max(count - 1, 0)], f"fewer than minItems {count}")
    if keyword == "uniqueItems":
        return (path, [deepcopy(current[0]), deepcopy(current[0])], "duplicate items")
    if keyword == "maxItems":
        element = deepcopy(current[0])
        grown = [deepcopy(element) for _ in range(count + 1)]
        # Part ids must stay unique or the fixture is invalid for two reasons at once.
        if path == "parts":
            for i, item in enumerate(grown):
                item["id"] = f"p{i}"
        return (path, grown, f"more than maxItems {count}")
    return None


def slug(pointer: str, keyword: str, target: str) -> str:
    raw = f"{pointer.lstrip('#').strip('/')}-{keyword}-{target}"
    out = "".join(ch if ch.isalnum() else "-" for ch in raw)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-").lower()[:110]


def main() -> int:
    # Only clear what this script produced. Fixtures prefixed `handwritten-` cover the
    # constraints the keyword walk cannot reach — chiefly the closed geometry vocabulary,
    # which the schema expresses as a `oneOf` rather than as a keyword on a value.
    INVALID_DIR.mkdir(parents=True, exist_ok=True)
    for existing in INVALID_DIR.glob("*.json"):
        if not existing.name.startswith(HANDWRITTEN_PREFIX):
            existing.unlink()

    constraints = enumerate_constraints(SCHEMA)
    written = 0
    covered: set[str] = set()
    unmapped: list[str] = []

    for cid, constraint in sorted(constraints.items()):
        pointer, keyword = constraint["pointer"], constraint["keyword"]
        site = pointer_to_site(pointer)
        if site is None:
            unmapped.append(cid)
            continue
        geometry, path = site

        spec = base_spec(geometry)
        try:
            get_path(spec, path)
        except (KeyError, IndexError, TypeError):
            # The site does not exist in the minimal base (an optional branch).
            unmapped.append(cid)
            continue

        if keyword in {"minItems", "maxItems", "uniqueItems"}:
            found = array_violation(constraint, path, spec)
            cases = [found] if found is not None else []
        else:
            cases = violations(constraint, path)

        if not cases:
            unmapped.append(cid)
            continue

        for target, value, note in cases:
            fixture = base_spec(geometry)
            try:
                mutated = set_path(fixture, target, value)
            except (KeyError, IndexError, TypeError):
                unmapped.append(cid)
                continue
            name = slug(pointer, keyword, target)
            payload = {
                "violates": keyword,
                "pointer": pointer,
                "target": target or "(whole document)",
                "note": note,
                "spec": mutated,
            }
            (INVALID_DIR / f"{name}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            written += 1
            covered.add(cid)

    print(f"constraints enumerated : {len(constraints)}")
    print(f"constraints covered    : {len(covered)}")
    print(f"fixtures written       : {written}")
    if unmapped:
        print(f"unmapped ({len(unmapped)}):")
        for cid in unmapped:
            print("   ", cid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
