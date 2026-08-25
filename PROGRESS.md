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

### Evidence

Backfilled 2026-08-25. Phase 0 was reported complete without this, which is the reason it
is being added now rather than at the gate.

**Two important caveats, stated before the output rather than after it.**

1. The terminal output below is from **HEAD (`737f64f`, Phase 1 complete)**, not from the
   Phase 0 commit. It therefore shows 513 pytest tests, not Phase 0's 41. Evidence for the
   Phase 0 commit itself is the CI run, which is linked below and does pin `8ec01d05`.
2. At the Phase 0 commit, `make codegen-check` **could not run on this machine at all**.
   `codegen.mjs` spawned `apps/web/node_modules/.bin/json-schema-to-zod`, which on Windows
   is an extensionless shim that `execFileSync` cannot execute:

   ```
   $ git show 8ec01d0:packages/scenespec/codegen.mjs | grep -n 'bin/json-schema-to-zod'
   44:const cli = resolve(repoRoot, "apps/web/node_modules/.bin/json-schema-to-zod");

   exists: true
   spawn FAILED: ENOENT - spawnSync C:\...
ode_modules\.bin\json-schema-to-zod ENOENT
   ```

   So the D7 drift test — a Phase 0 gate item — was only ever verified in Linux CI. It was
   fixed in Phase 1; that fix is why the run below succeeds.

#### Raw terminal output

Also committed verbatim at [`evidence/phase0/gate-commands.txt`](evidence/phase0/gate-commands.txt).

```console
Captured at HEAD 737f64f on 2026-08-25T13:11:45Z · Windows 11, Git Bash, node v24.13.1, Python 3.12.14

$ make codegen-check
./packages/scenespec/codegen.sh
zod   -> C:\Users\shiva\Desktop\Aakar\Aakar\apps\web\src\scenespec\generated.ts
pydantic -> services/api/aakar/scenespec/generated.py
warning: in the working copy of 'apps/web/src/scenespec/generated.ts', LF will be replaced by CRLF the next time Git touches it
no drift: generated types match the schema
$? = 0

$ cd services/api && AAKAR_PROVIDER_MODE=replay uv run pytest -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 84%]
........................................................................ [ 98%]
.........                                                                [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\shiva\Desktop\Aakar\Aakar\services\api\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_auth.py::test_ensure_owner_is_idempotent
  C:\Users\shiva\Desktop\Aakar\Aakar\services\api\.venv\Lib\site-packages\passlib\handlers\argon2.py:716: DeprecationWarning: Accessing argon2.__version__ is deprecated and will be removed in a future release. Use importlib.metadata directly to query for argon2-cffi's packaging metadata.
    _argon2_cffi.__version__, max_version)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
513 passed, 2 warnings in 7.62s
$? = 0

$ cd apps/web && npx tsc --noEmit
$? = 0   (no output is a clean typecheck)

$ docker compose config
name: aakar
services:
  qdrant:
    container_name: aakar-qdrant
    healthcheck:
      test:
        - CMD-SHELL
        - bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333' || exit 1
      timeout: 3s
      interval: 5s
      retries: 12
      start_period: 10s
    image: qdrant/qdrant:v1.12.1
    networks:
      default: null
    ports:
      - mode: ingress
        target: 6333
        published: "6333"
        protocol: tcp
      - mode: ingress
        target: 6334
        published: "6334"
        protocol: tcp
    restart: unless-stopped
    volumes:
      - type: bind
        source: C:\Users\shiva\Desktop\Aakar\Aakar\data\qdrant
        target: /qdrant/storage
        bind: {}
networks:
  default:
    name: aakar_default
$? = 0
```

#### CI

Run **32694854874** — workflow `CI`, event `push`, branch `main`, commit
`8ec01d05bca29e1c17572df944d339bf68b8c40c` (the Phase 0 gate commit), conclusion
**success**.

<https://github.com/ShivamMalge/Aakar/actions/runs/32694854874>

| job | status | conclusion |
| --- | --- | --- |
| `api (ruff + mypy + pytest)` | completed | success |
| `web (eslint + tsc + vitest)` | completed | success |
| `codegen drift (D7)` | completed | success |

The same three jobs also passed on the same SHA on branch `claude/markdown-review-yog81s`
(run [32655674007](https://github.com/ShivamMalge/Aakar/actions/runs/32655674007)). A third
run against that SHA, [32694859587](https://github.com/ShivamMalge/Aakar/actions/runs/32694859587),
is Dependabot's `Graph Update: uv` — not this workflow, listed so the run history reconciles.

**Not yet evidenced:** `docker compose config` validates the file, but the Qdrant
healthcheck still has not been exercised against a running container — the caveat recorded
when Phase 0 closed stands, and Phase 2 is where it has to be settled.


### Backfilled after the gate (2026-08-25)

Requested by the architect on the grounds that Phase 0's gate was never actually passed.

- **Cross-validator conformance corpus** — `packages/scenespec/fixtures/`. 6 valid + 220
  invalid fixtures, run through pydantic (`tests/test_conformance.py`) and zod
  (`src/scenespec/conformance.test.ts`). Both must agree on every fixture; a divergence
  fails whichever side is wrong. Wired into CI as named steps in the `api` and `web` jobs.

  The invalid fixtures are **derived from the schema**, not from a hand-kept list:
  `generate.py` walks `scenespec.schema.json`, enumerates all 190 constraints it declares,
  and violates each one. `test_every_schema_constraint_has_a_fixture` fails if a constraint
  gains no fixture, so the corpus cannot fall behind the schema.

  This exists because `codegen-check` compares generated **bytes** — a faithfully
  regenerated but vacuous validator passes drift while validating nothing, which is exactly
  what D-015 was and it was caught by reading the file. Measured against the corpus, the
  D-015 shape (`parts: z.array(z.any())`) accepts **211 of 220** invalid fixtures while
  accepting all 6 valid ones: it would have looked healthy and failed 211 corpus tests.

- **Cassette hermeticity** — `tests/test_cassette_hermeticity.py`. A replay miss raises
  `CassetteMiss` for chat, VLM and embeddings, and does not reach an inner provider *even
  when one is supplied*, which is the case where a fallthrough would cost real money.

- **Budget preflight** — `tests/test_budget_guard.py`. The guard is driven to an actual
  refusal with a spy provider asserting zero invocations. **It also records the gap:**
  `CostLedger` is not wired into `CassetteProvider`, so nothing calls `preflight`
  automatically. The tests prove the guard refuses when a call site invokes it — not that
  every call path does, because no call path does yet. Phase 2 is the first phase allowed
  to spend, so that is the boundary at which this stops being theoretical.

- **Owner scoping** — `tests/test_owner_scoping.py`. `owner_id` is asserted NOT NULL on
  exactly the seven registered tables, and any non-global table without it fails. All four
  tripwires were verified by negative control (an 8th table with no `owner_id`, with a
  nullable one, an unregistered one, and a new route) — each fails as intended.

  **Cross-owner route isolation could not be tested: no route serves an owner-scoped
  resource yet.** The whole surface is `/healthz`, `/auth/{login,logout,me}` and FastAPI's
  docs endpoints; none take a resource id. `test_no_route_serves_an_owner_scoped_resource`
  pins that surface so the first owner-scoped route cannot land without its 404 assertions.

- **Referential constraints (parent resolution, unique names, single root)** — reported to
  the architect, not implemented. See the answer recorded against the request; the decision
  on where that layer lives is the architect's.

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

### Fixed after the first capture round

- **`/render/[topic]` returned 500 once Next rebuilt its client manifest.** `page.tsx` is a
  server component and was reading `DEFAULT_OPTIONS.cutaway` off an export of `Viewer.tsx`,
  which is a `"use client"` module — every export of one is a client reference, not a value
  the server can read. The options moved to `src/viewer/options.ts`, a plain module both
  sides import. Worth flagging because the earlier screenshots were captured *before* the
  manifest rebuild surfaced it: the route was already broken while the evidence looked fine.
  All captures were regenerated after the fix.
- **Hovering a part did not change the cursor.** The interaction probe reported `auto`,
  which is what surfaced it; parts now show `pointer`, and the probe asserts it.

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
