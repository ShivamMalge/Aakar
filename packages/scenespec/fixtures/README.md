# Cross-validator conformance corpus

`codegen-check` compares generated **bytes**. A generator that regenerates faithfully but
emits a validator which accepts everything passes the drift test while validating nothing —
that is exactly what D-015 was, and it was caught by reading the output, not by a test.

This corpus closes that hole. Every fixture is run through **both** generated validators:
pydantic (`services/api/tests/test_conformance.py`) and zod
(`apps/web/src/scenespec/conformance.test.ts`). Each fixture declares the outcome it
expects, so if the two stacks ever disagree, whichever one is wrong fails its own suite.

## Layout

- `valid/*.json` — plain SceneSpec documents that **must be accepted**. No wrapper, so they
  double as real specs.
- `invalid/*.json` — documents that **must be rejected**, each wrapped with the constraint
  it violates:

  ```jsonc
  {
    "violates": "exclusiveMinimum",              // the JSON Schema keyword
    "pointer": "#/$defs/Sphere/properties/radius", // where that keyword lives
    "target": "parts.0.geometry.radius",         // where the document was mutated
    "note": "sphere radius must be > 0",
    "spec": { /* the offending SceneSpec */ }
  }
  ```

  The wrapper is outside the spec on purpose: putting metadata *inside* would trip
  `additionalProperties: false` and the fixture would then be rejected for the wrong reason.

## The coverage test

`test_conformance.py::test_every_schema_constraint_has_a_fixture` walks
`scenespec.schema.json` and enumerates every constraint keyword it finds. Adding a
constraint to the schema without adding a fixture fails that test — the enumeration comes
from the schema, not from a hand-maintained list.

## Regenerating

Most `invalid/` fixtures are produced by `generate.py`, which mutates a base spec carrying
one part of each of the nine geometry types. Hand-written cases live alongside them and are
never overwritten.

```
cd services/api && uv run python ../../packages/scenespec/fixtures/generate.py
```
