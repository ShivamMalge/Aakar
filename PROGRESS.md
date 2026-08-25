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

---

## Phase 1 — Compiler + viewer, zero LLM · **complete, awaiting approval**

Date: 2026-08-25 · Final `schema_version`: **1.0** (D-018 explains why it did not move)

### Built

- **1.1** Deterministic compiler (`apps/web/src/compiler/`): one builder per geometry type,
  transform + parent resolution, material mapping. Graph validator covers the three
  constraints JSON Schema cannot express — unique ids, resolvable parents, acyclic parent
  graph — and reports **every** error in one pass with a suggested near-miss id, because a
  repair round that fixes one problem per attempt burns D3's two-round budget.
- **1.2** `/render/[topic]`: R3F canvas, orbit/touch controls, raycast click → selection,
  hover outline, label billboards with a toggle. `?spec_version=` **refuses explicitly**
  rather than silently serving the approved spec (D-004 fails closed).
- **1.3** Cutaway from the spec's plane, `clip_exempt` honoured, UI toggle.
- **1.4** Exploded view, slider-controlled, both G-10 candidate modes implemented and
  rendered — ruling in D-017.
- **1.5** Three golden specs hand-written: `human_eye` (12 parts), `earth_layers` (5),
  `animal_cell` (13). Every part carries a name and ≥1 alias; a test asserts it.
- **1.6** Playwright harness driven from `services/api` (D-009), CLI over the same
  `capture()` the Phase 3 critic will call. `make shots` reproduces the gate captures.
- **1.7** 95 vitest tests. fast-check property tests (D-001) cover compiler totality,
  NaN-freedom, explode/clip safety, and factor-0 identity.

### Decisions taken during the phase

- **D-017 — exploded view moves top-level parts only** (closes G-10). Made by looking at
  both renders: `per-part` pulls the nucleolus half out of its own nucleus.
- **D-018 — `Geometry` gets an OpenAPI `discriminator`.** This fixed a real cross-stack
  drift the Phase 0 gate could not see: zod inferred `geometry` as `any` **and applied no
  geometry defaults**, while pydantic applied them all. Same schema, two behaviours.
  `schema_version` deliberately stays `1.0` — no validation semantics changed.
- **D-019 — golden specs omit `provenance.evidence`.** There is no chunk to quote from
  yet; a fabricated quotation in a field whose contract is "quoted from the source" is
  worse than an absent one.
- **D-020 — translucent parts do not write depth.** Without this every layered topic
  renders as one flat grey ball.
- **D-021 — a cutaway normal points away from `camera_hint`.** The first golden specs
  clipped the far hemisphere: correct, invisible, and indistinguishable in a screenshot
  from clipping being switched off.

### Fixed en route

- **`codegen.mjs` could not run on Windows.** It spawned `node_modules/.bin/json-schema-to-zod`,
  which is an extensionless shim there — `ENOENT`. It now resolves the generator's real
  entrypoint and runs it under the current `node`. The D7 drift test was unrunnable on this
  platform until this was fixed.
- **Stray `services/api/apps/web/`** — byte-identical copies of the web layout and page,
  committed in Phase 0 from a scaffold run in the wrong directory. Deleted; no tooling
  covered it, so it would have rotted silently.
- **`apps/web/tsconfig.tsbuildinfo`** was tracked. Now ignored.

### Known issues carried forward

- **No dev-server guard on `make shots`.** The harness assumes the web app is already up
  and fails with a Playwright timeout if it is not. Phase 3's batch runner needs to start
  and stop the server itself (D-009 says `make dev` and the batch runner both ensure it);
  that wiring is a Phase 3 task, not a Phase 1 one.
- **Labels have no collision avoidance.** Anchoring each label on its part's surface rather
  than its centre fixed the concentric case — Earth's five layers were five labels on one
  pixel — but genuinely clustered parts still overlap. The eye's anterior segment is the
  worst case. Acceptable with the toggle; revisit if Phase 4's mobile QA finds it unusable.
- **A fully exploded concentric topic needs the camera to pull back.** Implemented as a
  dolly tied to the explode factor. It scales by the *change* in factor, so a reader's own
  zoom survives, but it does mean the slider moves the camera.
- **`uv` and Python 3.12 were absent on this machine** and were installed to run the Python
  stack at all. Worth noting in case the environment is rebuilt.
