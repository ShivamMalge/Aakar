# Aakar (आकार — form)

Upload a chapter → an LLM emits a structured **SceneSpec** → a deterministic renderer
builds a labeled, clickable 3D model → clicking any part opens a RAG panel grounded in
your own material, with page citations.

**Status: Phase 0 (scaffold + schema + codegen).** The viewer arrives in Phase 1; nothing
calls a model until Phase 2. See `phases.md` for the roadmap, `DECISIONS.md` for every
choice made and why, `GAPS.md` for what is still unmeasured.

The full README — with both headline claims linked to evidence — is a Phase 5 deliverable.

## Layout

```
apps/web/            Next.js: viewer, panel, admin review, library
services/api/        FastAPI: ingest, retrieve, generate, critic, cache
packages/scenespec/  scenespec.schema.json — the single source of truth (D7)
specs/golden/        hand-written Phase 1 specs
evidence/            gate screenshots & transcripts (committed; open corpus only — D-005)
```

## Getting started

```bash
cp .env.example .env      # AAKAR_AUTH_SECRET must be >= 32 bytes
make install              # both stacks
make browser              # Playwright chromium (D-009)
make test                 # pytest + vitest, replay mode — no key, no spend
make codegen-check        # the D7 drift test
make dev                  # api :8000, web :3000
```

## The one rule to read first

`scenespec.schema.json` is the single source of truth. The zod and pydantic types are
**generated** — never hand-edit `apps/web/src/scenespec/generated.ts` or
`services/api/aakar/scenespec/generated.py`. Change the schema, run `make codegen`, commit
both outputs. CI fails otherwise.
