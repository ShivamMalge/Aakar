# PROGRESS.md

Running log. One entry per phase gate, per spec §10.

---

## Phase 0 — Scaffold + schema + codegen · **complete, awaiting approval**

Date: 2026-08-23 · Branch: `claude/markdown-review-yog81s`

### Built

- **0.0** Governing documents committed (`aakar-claude-code-prompt.md` v1.1, `phases.md`).
- **0.1** Monorepo: `apps/web` (Next.js 14 App Router, TS strict), `services/api`
  (Python 3.12, FastAPI, uv), `packages/scenespec`. Makefile drives both stacks.
- **0.2** `docker-compose.yml` — Qdrant only, with a healthcheck. **See caveat below.**
- **0.3** `scenespec.schema.json` per spec §4: nine geometry types, ≤40 parts, mandatory
  provenance, hex colors, numeric bounds throughout.
- **0.4** Codegen → zod + pydantic; `make codegen-check` is the drift test.
- **0.5** SQLite: `users`, `documents`, `corpora`, `topics`, `spec_versions`, `approvals`,
  `llm_calls`, `qa_cache_meta`. `owner_id` on all seven user-scoped tables (D-011);
  `qa_cache_meta.corpus_id` is NOT NULL (D-007).
- **0.6** Provider abstraction — chat/VLM/embeddings behind one interface, `live|record|replay`
  cassette, cost ledger, budget preflight.
- **0.7** Owner session — pyjwt HS256 + argon2, `require_owner`, `/auth/*`.
- **0.8** CI: three jobs (api, web, drift), all in replay mode with no API key.

### Decisions taken during the phase

- **Zod v4, not v3.** `json-schema-to-zod` emits v4 idioms (`z.core.$ZodIssue`); with zod
  v3 installed, `tsc` failed on the generated file. Logged as D-014.
- **The schema is dereferenced before zod codegen.** `json-schema-to-zod` does not follow
  `$ref` into `$defs` — it emits `z.any()`, which would have made the zod side validate
  nothing while appearing to work. Logged as D-015.
- **`AAKAR_AUTH_SECRET` must be ≥32 bytes.** PyJWT warned that shorter HS256 keys weaken
  the MAC (RFC 7518 §3.2); `Settings.from_env()` now refuses at boot. Logged as D-016.
- **`--enum-field-as-literal all`** for pydantic codegen: datamodel-code-generator emits
  `Importance | None = Field("core")`, a raw string where the enum is expected, which
  mypy strict rejects. Literals are type-correct and round-trip JSON more directly.

### Known issues carried forward

- **The Qdrant healthcheck is unverified.** No Docker daemon in this environment
  (`/var/run/docker.sock` absent), so `docker compose up` could not run. `docker compose
  config` validates the file, but the healthcheck command itself — `bash -c` against
  `/dev/tcp` — has not been exercised against the real image. Phase 0 needs no running
  Qdrant; **verify this at the start of Phase 2**, which is the first phase that does.
- **passlib 1.7.4 imports the `crypt` module**, removed in Python 3.13. Harmless on the
  pinned 3.12 and it emits a DeprecationWarning today. Revisit before any 3.13 move;
  `argon2-cffi` used directly is the exit.
- **`npm audit` reports 10 vulnerabilities** in the transitive dev tree. None are in
  runtime dependencies. Triage before Phase 4, not now.
