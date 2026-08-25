"""Canonical form for a parsed SceneSpec — Python side.

Verdict agreement is not behavioural agreement. Both generated validators can accept the
same document and still hand back *different values*: before D-018, zod applied no
geometry defaults while pydantic applied them all, so a lathe with no `segments` reached
the web compiler as `undefined` and the API as `32`. The verdict corpus could not see
that, because both stacks said "valid".

Canonicalising both outputs and deep-comparing them is what sees it. The rules are
deliberately small, and `canonical.ts` implements exactly the same ones:

1. object keys are sorted lexicographically
2. keys whose value is null/undefined are dropped — an absent optional and an explicit
   null are the same document, and the two stacks spell it differently
3. an integral number is emitted as an integer, so 1.0 and 1 do not differ across
   languages; anything else is rounded to 12 decimal places
4. array order is preserved, because it is meaningful
"""

from __future__ import annotations

import json
from typing import Any

DECIMALS = 12


def canonical(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        rounded = round(value, DECIMALS)
        return int(rounded) if rounded == int(rounded) else rounded
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items()) if v is not None}
    return value


def dumps(value: Any) -> str:
    return json.dumps(canonical(value), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _resolve(node: Any, schema: dict[str, Any]) -> Any:
    """Follow a local $ref one hop; the schema has no chains and no cycles."""
    if isinstance(node, dict) and "$ref" in node:
        name = str(node["$ref"]).replace("#/$defs/", "")
        target = dict(schema["$defs"][name])
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        target.update(siblings)
        return target
    return node


def apply_defaults(document: Any, subschema: Any, schema: dict[str, Any]) -> Any:
    """Fill in every schema-declared default the document omitted.

    This is what the expected form is built from — *the schema*, not either parser. If it
    were generated from one stack, that stack's bug would become the expected answer.
    """
    subschema = _resolve(subschema, schema)
    if not isinstance(subschema, dict):
        return document

    if "oneOf" in subschema:
        discriminator = subschema.get("discriminator", {}).get("propertyName")
        for branch in subschema["oneOf"]:
            resolved = _resolve(branch, schema)
            if discriminator is None or not isinstance(document, dict):
                continue
            const = resolved.get("properties", {}).get(discriminator, {}).get("const")
            if const == document.get(discriminator):
                return apply_defaults(document, resolved, schema)
        return document

    properties = subschema.get("properties")
    if isinstance(properties, dict) and isinstance(document, dict):
        out = dict(document)
        for key, sub in properties.items():
            resolved = _resolve(sub, schema)
            if key in out:
                out[key] = apply_defaults(out[key], sub, schema)
            elif isinstance(resolved, dict) and "default" in resolved:
                out[key] = resolved["default"]
        return out

    items = subschema.get("items")
    if items is not None and isinstance(document, list):
        return [apply_defaults(item, items, schema) for item in document]

    return document


def observe_defaults(
    document: Any, subschema: Any, schema: dict[str, Any], pointer: str = "#"
) -> dict[str, str]:
    """Report, per defaulted schema field, whether this document supplied it.

    Returns {schema_pointer: "present" | "absent"}. The meta-test uses it to prove the
    corpus exercises every defaulted field both ways — "absent" is where defaults
    divergence lives, and a corpus that only ever supplies a value cannot see it.
    """
    seen: dict[str, str] = {}
    resolved = _resolve(subschema, schema)
    if not isinstance(resolved, dict):
        return seen

    if "oneOf" in resolved:
        discriminator = resolved.get("discriminator", {}).get("propertyName")
        for branch in resolved["oneOf"]:
            branch_resolved = _resolve(branch, schema)
            if discriminator is None or not isinstance(document, dict):
                continue
            const = branch_resolved.get("properties", {}).get(discriminator, {}).get("const")
            if const == document.get(discriminator):
                ref = str(branch.get("$ref", "")).replace("#/$defs/", "")
                base = f"#/$defs/{ref}" if ref else pointer
                return observe_defaults(document, branch_resolved, schema, base)
        return seen

    properties = resolved.get("properties")
    if isinstance(properties, dict) and isinstance(document, dict):
        for key, sub in properties.items():
            child_pointer = f"{pointer}/properties/{key}"
            sub_resolved = _resolve(sub, schema)
            if isinstance(sub_resolved, dict) and "default" in sub_resolved:
                seen[child_pointer] = "present" if key in document else "absent"
            if key in document:
                ref = str(sub.get("$ref", "")).replace("#/$defs/", "") if isinstance(sub, dict) else ""
                base = f"#/$defs/{ref}" if ref else child_pointer
                seen.update(observe_defaults(document[key], sub, schema, base))
        return seen

    items = resolved.get("items")
    if items is not None and isinstance(document, list):
        ref = str(items.get("$ref", "")).replace("#/$defs/", "") if isinstance(items, dict) else ""
        base = f"#/$defs/{ref}" if ref else f"{pointer}/items"
        for element in document:
            seen.update(observe_defaults(element, items, schema, base))
    return seen


def defaulted_pointers(schema: dict[str, Any]) -> set[str]:
    """Every schema location carrying a `default`, as a pointer."""
    found: set[str] = set()

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            if "default" in node:
                found.add(pointer)
            for key, child in node.items():
                walk(child, f"{pointer}/{key}")
        elif isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, f"{pointer}/{i}")

    walk(schema, "#")
    return found
