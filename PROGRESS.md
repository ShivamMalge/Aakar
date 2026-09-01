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

---

## Phase 1 — corrections · 2026-08-25

Requested by the architect before Phase 1 approval. Rulings A–C and work items 1–6.

### Rulings applied

- **A** — `parent_id` resolution and acyclicity are **enforced on both stacks, at parse**
  (D-023). Unique names and single-root **dropped**, and recorded as fixtures that must be
  *accepted* so nobody adds them back by accident.
- **B** — `instance_of` added; **schema_version 1.1** (D-022). Unlike D-018 this is a real
  validation-semantics change, so the version moved.
- **C** — noted, not done: `CostLedger` is still not wired into `CassetteProvider`. It is the
  first task of Phase 2 and `test_the_guard_is_not_wired_into_the_provider` still fails the
  moment it lands.

### Work

1. **Behavioural conformance.** 34 fixture pairs over every defaulted field (present and
   absent) and every geometry variant. Both stacks parse, canonicalise and deep-compare
   against an expected form derived from **the schema** — not from either parser, or one
   stack's bug becomes the expected answer. Coverage meta-test fails if a defaulted field
   lacks a present/absent pair. Wired into CI in both jobs.

   Retrospective, measured: with the discriminator reverted, **the behavioural axis fails 6
   of 35 and the verdict axis fails 0 of 231.** The old corpus was completely blind to D-018.

2. **Capture liveness.** `screenshots.py` now asserts HTTP 200 and a compiler-backed sentinel
   node — carrying topic, part count and schema version — before any capture, and refuses to
   write a PNG past a failed precondition.

   **The retrospective changed the design.** Re-breaking the route showed the original
   incident was worse than reported: the capture URL supplies every option explicitly, and the
   fault only occurred when an option was *absent*, so `/render/{topic}` — what readers and
   share links open — returned 500 while the harness URL returned 200. A harness that only
   ever visits its own over-specified URL cannot see that class at all. `capture()` now checks
   the **default route** for each topic before capturing.

3. **Validator placement.** Moved to `packages/scenespec` with a Python mirror, firing at
   parse on both stacks, one fixture set driving both (D-023). Writing the fixtures found a
   real defect: a self-parent was reported twice, under two different codes.

4. **Containment warnings** (D-024). Two on the golden specs, both legitimate:
   `nuclear_envelope → nucleus` 0.770 and `fovea → retina` 0.857.

5. **Stress fixture** — `specs/stress/neuron.json`, 40 parts at the cap, depth 6, all nine
   geometry types, 13 `instance_of` groups over 31 parts, one `clip_exempt`.

   Building it found the same nested-transform trap twice: a rotated part turns its **whole
   subtree**, so a −90° rotation on the axon hillock rendered the entire axon at right angles
   to where it was authored. The generator now refuses to emit a rotated or scaled part that
   has children. Worth carrying into Phase 3 — a generated spec has no such guard.

   Its first `camera_hint` was copied in the shape of a 1-unit topic and cropped a 6-unit
   assembly at both ends. A generator copying a golden spec's `camera_hint` onto a larger
   topic will do exactly this.

6. **`make codegen-check` on Windows** — confirmed working; see the Phase 0 evidence block for
   why it could not run at the Phase 0 commit.

### Carried forward

- **Label density at 40 parts is unusable.** Legible at 5–13; at the cap the labels overlap
  badly. Collision avoidance was already a known gap and the stress fixture sets its real
  size. Phase 4's mobile QA is where this has to be settled.
- **The containment threshold (0.9) is calibrated against three hand-written specs.**
  Recalibrate against Phase 3's generated ones.
- **AABB containment over-reports for spheres** — the fovea warning is geometry crudeness, not
  a spec defect.

---

## Phase 1 — second correction round · 2026-08-26

Items 7–12 and the Phase 2 amendment. **Phase 2A not started.**

### Schema 1.2

`chunk_ids` may now be empty (D-025). This reverses the Phase 1 finding that a part with no
provenance was inexpressible, and it is the most consequential change in the round: requiring
a citation forced a model with nothing to cite to cite the nearest plausible chunk, making
**fabricated provenance mandatory**. A derived `provenance_strength` — `strong` / `weak` /
`none` — is computed at parse on both stacks and is never author-supplied.

**One deviation, flagged rather than buried.** The ruling defines strong as "a chunk naming
the part", which needs chunk text; no corpus exists at parse. Parse derives the document's
*claim* (`evidence` present ⇒ strong), and D-008's Phase 3 check verifies it against real
chunk text and may downgrade. Full reasoning in D-025.

### Work

| item | outcome |
| --- | --- |
| 7 · capture split | `capture()` emits unlabeled (critic) and labeled (curator) per view; variant always in the filename. 30 PNGs regenerated. |
| 8 · label layout | Pure-function layout: leader lines, collision displacement, depth-tested anchors, drop-by-`importance`. First consumer of `importance` (D-006). |
| 9 · camera + materials | Bounds-derived framing; shelled topics open cut away. Sclera diagnosed and 6 material values corrected in the specs. |
| 10 · zero provenance | Schema 1.2, `provenance_strength`, fixtures for all three states on both stacks. |
| 11 · rotated parents | Prohibition reversed — it was one `assert` in the stress-fixture build script. Now a warning. |
| 12 · containment | Real-geometry containment + five-way relation classification. **Zero warnings on all four specs.** |

### Measured

Label placement at 1280×900, after the occlusion fixes:

| topic | parts | placed | dropped | occluded | no space |
| --- | --: | --: | --: | --: | --: |
| `human_eye` | 12 | 12 | 0 | 0 | 0 |
| `earth_layers` | 5 | 5 | 0 | 0 | 0 |
| `animal_cell` | 13 | 7 | 6 | 6 | 0 |
| `neuron` | 40 | 38 | 2 | 2 | 0 |

`animal_cell` and `neuron` drops are all occlusion — parts on the cut-away side of the plane,
or genuinely behind opaque geometry. **Nothing is dropped for lack of space at this viewport**,
which is the number that matters for the 40-part cap.

Parent relations, after D-026:

| topic | parented | contained | surrounds | surface | adjacent | detached |
| --- | --: | --: | --: | --: | --: | --: |
| `animal_cell` | 2 | 1 | 1 | 0 | 0 | **0** |
| `earth_layers` | 0 | — | — | — | — | **0** |
| `human_eye` | 1 | 0 | 0 | 1 | 0 | **0** |
| `neuron` | 39 | 8 | 0 | 11 | 20 | **0** |

### Three findings worth the architect's attention

1. **The over-specification trap appeared a third time.** `ShotRequest` pinned `cutaway=0` on
   every capture URL, so the new geometry-derived default could never fire in a capture — every
   gate image silently showed the non-default path. Same shape as the Phase 1 outage (a fault
   reachable only when an option was *absent*) and as the `camera_hint` distance. `cutaway` is
   now tri-state. **This class recurs; it is worth a standing rule that harness parameters must
   be able to say "unspecified".**

2. **`parent_id` semantics do not cover branching topologies.** D-017 defines it as "is
   contained by", but the neuron's 39 parented pairs are 20 `adjacent` and 11
   `surface_attached` — it parents by *connectivity*, which is what makes its exploded view
   carry subtrees correctly. The classification describes this rather than excusing it, but
   D-017's wording is narrower than the thing it governs. **Ruling wanted.**

3. **Two silent label-blanking bugs, both invisible in a still.** The raycaster has no notion
   of transparency (a 0.45-opacity soma blanked every organelle inside it) and none of clipping
   planes (in cutaway, `human_eye` placed 1 label of 12 while all 12 were plainly on screen).
   Both were found only by reading the counts, not by looking at the image — which is why the
   counts are now on the capture sentinel.

### Carried forward

- **Label density is resolved at 1280×900 and untested on a phone.** Zero dropped-for-space
  here says nothing about a 390px viewport; Phase 4's mobile QA is where it gets settled.
- **The containment thresholds are calibrated against four hand-authored specs.** Recalibrate
  against generated ones in Phase 3, per the standing note.
- **`provenance_strength` is provisional at parse** until D-008's evidence check runs against
  real chunk text (Phase 3).
- Golden specs are uniformly `weak` until the 2B.11 backfill; a test pins that so the change is
  visible when it lands.

---

## Phase 2A — Ingestion, corpus addressing, ingest limits · **complete, awaiting approval**

Date: 2026-08-26 · Rulings applied first (D-030…D-033), then 2A.1–2A.7.

### Built

- **2A.1 `CostLedger` wired into `CassetteProvider`**, before anything else. The preflight
  sits *after* the cassette and *before* the provider, so a replayed or cached call returns
  above it and costs nothing, while every call that would actually spend is checked first.
  Every call is logged, hit or miss — a cache hit that left no trace would make Phase 2B's
  hit rate unmeasurable.
- **2A.2 Content-addressed corpora** (D-029). `corpora` lost `owner_id` and gained a unique
  `content_hash`; access moved to `corpus_grants`. Migration v1→v2 included and tested:
  every v1 corpus becomes a content-addressed row plus a grant to its former owner, so
  nobody loses access. It runs *before* `apply_schema`, because `CREATE TABLE IF NOT EXISTS`
  cannot reshape a table that already exists.
- **Ruling (e) — group grants.** `groups`, `group_members`, and `corpus_grants` holding
  `owner_id` XOR `group_id` under a CHECK. No routes, no tier logic, no UI. The reachability
  query is written once in `can_read` so the shape is demonstrably usable.
- **2A.3 Ingest hard limits**, enforced on raw bytes before any parse. Numbers proposed
  below.
- **2A.4 Encrypted / unparseable rejection** with an actionable remedy on every code.
- **2A.5 Chunk storage** with per-chunk `warnings_json` **and** a `warning_scope` column.
- **2A.6 Page label vs page index** as two separate columns, neither inferred from the other.
- **2A.7 Qdrant healthcheck verified** against the real image, with a negative control.

### The table partition replaces the owner_id registry

D-011 asked "does every user-scoped table carry `owner_id`". That is no longer the whole
question. Every table now sits in exactly one category with its own invariant, and the
partition is asserted total — so a new table cannot land without someone deciding which
access rule governs it.

| category | tables | invariant |
| --- | --- | --- |
| `owner_scoped` | documents, topics, spec_versions, approvals, llm_calls, qa_cache_meta | `owner_id NOT NULL` |
| `content_addressed` | corpora, chunks | no owner column; reached by grant |
| `grant` | corpus_grants | `owner_id` XOR `group_id` |
| `identity` | users, groups, group_members | principals, not resources |
| `meta` | schema_meta | belongs to the database |

### Proposed ingest limits — for approval or adjustment

Rationale throughout: LightningParse OCR runs at ~25 s/page, so a 400-page scan is ~3
CPU-hours **for one upload with no LLM call**. No budget guard fires, because nothing is
spent. This is a denial-of-service surface.

| limit | proposed | reasoning |
| --- | --- | --- |
| `max_bytes` | 64 MiB | a 400-page text PDF is 5–20 MB; clears a scanned chapter, refuses an archive dump. Checked first because it costs nothing |
| `max_pages` | 120 | the product's unit is a *chapter* (spec §1); chapters run 20–60 pages. Accepts a generous chapter, refuses a book |
| `max_ocr_pages` | 40 | the expensive one — ~17 min CPU. Deliberately well below `max_pages`: a born-digital 120-page PDF is cheap, a 120-page scan is 50 minutes |
| `max_documents_per_day` | 20 | per owner |
| `max_pages_per_day` | 400 | ~10 chapters/day; caps one account at ~2.8 CPU-hours even if every page needs OCR |

A document over `max_ocr_pages` is **refused, not partially OCR'd** — the uploader is told
rather than left with a silently incomplete corpus. Rejection is explicit at upload and
never a queue, because a queue turns a rejection into a resource commitment that merely
happens later.

### Gate evidence

`evidence/phase2a/dedupe-ledger.txt` — two owners upload byte-identical files:

```
alice  -> corpus cor_062769e3a71b | created=True  granted=True  | embedded (new corpus)
bob    -> corpus cor_062769e3a71b | created=False granted=True  | SKIPPED embedding

corpora        1
documents      2
corpus_grants  2

owner                  kind       mode     hit       usd
usr_697be004a05e4271   embedding  record   0      0.0040
TOTAL                                             0.0040
```

**One corpus, two documents, two grants, one embedding cost.** A different file produces a
second corpus that the other owner cannot read.

`evidence/phase2a/qdrant-healthcheck.txt` — 2A.7, closed:

```
image: qdrant/qdrant:v1.12.1   health: healthy   FailingStreak: 0
$ bash -c "exec 3<>/dev/tcp/127.0.0.1/6333"   -> exit 0
NEGATIVE CONTROL, port 9999                   -> exit 1  (Connection refused)
$ curl -s localhost:6333/healthz              -> healthz check passed
```

### Two blockers, reported rather than worked around

1. **LightningParse is unavailable.** Not installed, not on PyPI — it is Shivam's own
   library (spec §3). Chunking, page-numbered text extraction and the warnings array all
   belong to it.

   **So 2A.5's question — are the warnings per-chunk or per-document? — is UNANSWERED,
   because the library could not be run.** Rather than guess, `warning_scope` is stored per
   row and defaults to `unknown` for anything written without having seen the parser. The
   cost of that column is one string per chunk; the cost of assuming per-chunk resolution
   that does not exist is a UI attributing a document-wide warning to one paragraph — which
   is a provenance claim, the exact class D-030 exists to stop. Nothing here imports, wraps
   or reimplements LightningParse.

   `pypdf` was added for the **boundary only**: page count, encryption detection and page
   labels. It is not a parser substitute and does no chunking.

2. **The upload route does not exist yet.** 2A built the ingest boundary as a library with
   the limits, dedupe and rejection all tested, but no HTTP endpoint calls it — so
   `test_no_route_serves_an_owner_scoped_resource` still passes. The route needs the parser
   to be useful, and wiring it to a stub would produce a demo that stops working the moment
   the real parser lands.

### Found while building

- **An encrypted PDF was being classified `unparseable`.** `pypdf.decrypt()` *returns* a
  failure code rather than raising, so the broad except never fired and the uploader got
  "check it opens in a PDF viewer" for a file that opens perfectly. Caught by asserting on
  the remedy text, not just the exception type.
- **`llm_calls.kind` is a closed vocabulary** (`chat`/`vlm`/`embedding`) while the cassette
  keys on `embed`. Mapped at the boundary rather than loosening the CHECK, so a typo'd kind
  still fails the insert instead of quietly creating a category.

### Carried forward

- The upload route, real chunking, and the `warning_scope` answer all need LightningParse.
- Ingest limit numbers are **proposed**, not settled.
- Qdrant is verified healthy but nothing writes to it yet — collections land in 2B.

---

## Phase 2B (items 8–12) — spend controls · **complete, awaiting approval**

Date: 2026-08-27. Rulings first, then 2B.8–2B.12. Retrieval (2B.1–2B.7 in the roadmap's
own numbering) is untouched; this round is the economics and the failure modes.

### Built

- **2B.8 Model tiering.** Two tiers, configured separately, **recorded in the ledger by
  tier** — the tier is a call-site fact, not inferred from the model name, so a deployment
  using one model for both still produces a truthful split.
- **2B.9 Semantic QA cache.** Keyed `(corpus_id, part scope, question embedding)`. Parts
  sharing an `instance_of` are **one cache scope** (D-022), so two mitochondria share
  answers. Cross-corpus isolation is structural: `corpus_id` is in the SQL filter, so the
  similarity search only ranks what is already reachable.
- **2B.10 Per-owner question quota**, separate from the global budget. Both must pass.
- **2B.11 Degraded mode**, with the three causes distinguished per D-035.
- **2B.12 Registration ceiling** with a waitlist, default 25.

### Threshold calibration — measured, both sides (G-03)

`evidence/phase2b/cache-calibration.txt`:

```
threshold  false hits   hit rate   hits  misses  rejected  verdict
     0.80           3      100%      5       0         2  UNSAFE - answers questions not asked
     0.85           0       60%      3       2         5  usable
     0.90           0       40%      2       3         5  usable
     0.92           0       40%      2       3         5  usable
```

**0.80 scores a 100% hit rate and three false hits.** That is the failure the amendment
warned about, demonstrated rather than asserted: hit rate alone is trivially maximised by
lowering the threshold, at which point the cache answers questions the student did not ask —
fluently, cited, and about the right part. One false hit disqualifies a threshold outright;
it is absolute rather than a rate, because there is no hit rate that buys back a confidently
wrong answer.

**Scope limit, stated plainly:** this uses a deterministic bag-of-words embedder, because 2B
runs in replay with no key and no spend. It calibrates the **method** and proves the
two-sided harness works. **The number must be re-measured against the real embedder on the
real corpus before it is trusted.** D4's 0.92 is safe here, but "safe on a synthetic
embedder" is not the claim that matters.

### Gate evidence

`evidence/phase2b/gate.txt`:

| gate item | result |
| --- | --- |
| cache hit rate, two owners, one corpus | **5/5 = 100%**, second reader's marginal cost **$0.0000** |
| ledger tier split | `generation $0.1000 / 2 calls`, `answer $0.0100 / 10 calls` |
| per-owner quota | alice **REFUSED** at 5/5; bob **ALLOWED**, unaffected |
| provider hard-disabled | `CassetteMiss`; cached answer still served, library readable, **no 500** |
| ingest limits at the boundary | 2A, unchanged and still green |

Degraded mode, and why the causes had to stay separate:

```
budget exhausted:     upload=True  generate=False  cached=True
worker stalled:       upload=False generate=True   cached=True
```

A stalled worker stops **uploads** while questions keep working. A merged "unavailable"
state would have told the student their questions were down when they were not.

### Numbers proposed

| control | value | reasoning |
| --- | --: | --- |
| `max_questions_per_day` | 100 | a student asks tens per chapter; a count rather than a spend, because a student cannot feel dollars |
| `max_accounts` | 25 | deliberately far below the 500 the ingest bounds were reasoned against — a ceiling to raise deliberately, not discover by being overrun |
| `max_concurrent_ocr` | 2 | OCR is CPU-bound; raising it on a saturated machine lengthens every job instead of adding throughput |
| `max_queue_depth` | 50 | ~7 hours of backlog at 2 concurrent; beyond that a queued job is indistinguishable from a lost one |

### Not built, and why

- **Retrieval itself** (hybrid BM25 + dense, widening, summary cards, the panel UI).
  2B.8–2B.12 was the requested scope. The cache and tiering are the layers *around*
  retrieval and are testable without it; the transcripts and citation-accuracy items need
  the retrieval that is not yet written.
- **The `/ask` route.** The controls exist as a library with their refusals tested. Wiring a
  route before retrieval exists would mean stubbing the answer, and a stub would make the
  quota and cache demos measure nothing.

### Carried forward

- The threshold number is method-calibrated only; re-measure on the real embedder.
- Qdrant is verified healthy but still holds no collections — chunk indexing lands with
  retrieval.
- A "processing" state now exists in the product and the UI does not account for it
  (recorded in D-035, not built).

---

## OCR investigation · 2026-08-27 (pre-2C)

Asked before starting 2C: is OCR (a) opt-in, (b) Tesseract-dependent, or (c) absent?

**(b), and it works.** Evidence in `evidence/phase2c/ocr-investigation.txt`; full reasoning
in D-038.

Two of my own earlier claims were wrong, and both mattered:

1. **"A text-layer-free PDF produces zero blocks."** I had tested with `add_blank_page`,
   which makes a genuinely empty page — that correctly yields nothing and was never evidence
   about OCR. A real scan (a text PDF rasterised to JPEG and re-wrapped) parses with
   `tier: "scanned"` and blocks carrying `source: "ocr"`.
2. **"0.4.1 emits no warnings array."** `metadata.warnings` is an *optional* key, present
   only when there is something to report. Every document I had measured was clean. It is
   **per-document** — which is the answer 2A.5 asked for (D-039).

**The 25 s/page figure does not hold: measured 3.3–3.8 s/page, ~6.6x faster.** Every limit
rationale is restated in D-038; the numbers are unchanged pending approval, with one
recommendation to raise `max_ocr_pages` 40 → 80, since 40 currently rejects a scanned
chapter of 40–60 pages, which is a primary case.

**Tesseract is now a deployment requirement** (D-038), noted in the README and combined with
D-035 it rules out serverless *and* most managed Python runtimes for the ingest component.

Also landed: a corpus with zero chunks is never created — the job fails with
`no_extractable_text` instead. And the two rulings: the derived relation now comes from
`compile()` and rides the sentinel (D-040), and the cache threshold defaults to 0.92 as
config rather than a constant (D-041).

---

## Phase 2C — retrieval and `/ask` · **complete, awaiting approval**

Date: 2026-08-27. Pre-2C items first (`max_ocr_pages` 40 → 80, per-job timeout), then 2C.

### Pre-2C

- **`max_ocr_pages` 40 → 80**, as approved.
- **Per-job wall-clock timeout, 1800 s** (D-042). Implemented as a **killable subprocess**,
  not a thread: `parse_pdf` is one blocking call into Rust, and a thread cannot be killed,
  so abandoning one would free the worker slot in name only. On expiry the job fails with
  `timed_out:` — **distinguished from a parse failure**, because the document may be valid
  and merely slow, and only a timeout is worth retrying on a quieter system.

### Built

| item | outcome |
| --- | --- |
| 2C.1 chunking + embedding into Qdrant | model and dimensionality recorded in **D-043 before the collection existed**; `ensure_collection` refuses a width mismatch |
| 2C.2 part-scoped retrieval | scope = name + aliases, or `instance_of` where present (D-022) |
| 2C.3 relevance floor | `Retrieval.covered`; below it, a first-class "not in your chapter" result |
| 2C.4 `/ask` ordering | grant → **cache** → quota → budget → retrieval → answer tier |
| 2C.5 citations | `Citation.render()` is the only formatter, and it renders the **label** |
| 2C.6 provenance resolution | `unverified` → `weak`/`strong` from real chunk text, with `source` as a second axis (D-044) |

### Gate evidence

`evidence/phase2c/gate.txt` — a real PDF with **front matter**, so labels diverge from
indices, ingested through the real worker into a real Qdrant:

```
page labels read from the PDF: ['i', 'ii', '1', '2', '3']

chunk   index  label  source   text
2           2      1  digital  The lens is a transparent biconvex structure
```

| gate item | result |
| --- | --- |
| answer with correct page labels, hand-verified | **`[p. 1]`** for the sentence at page **index 2** — rendering the index would have printed `[p. 2]` |
| absent question → below-threshold, not fabricated | `kind=not_in_chapter`, **zero citations** |
| zero-provenance part → no citations, says so | `kind=no_provenance`, strength `none`, zero citations |
| cache hit consumes no quota, no budget | quota **0**, answer still served, `llm_calls 0 → 0` |
| re-measured threshold with false-hit counts | method closed, **number open** — see below |

`evidence/phase2c/cache-recalibration.txt`, at production dimensionality (768):

```
threshold  false hits   hit rate   verdict
     0.70           3      100%    UNSAFE - answers questions not asked
     0.80           3       80%    UNSAFE - answers questions not asked
     0.85           0       80%    usable
     0.92           0       40%    usable      <- configured default
```

### The one gate item not fully closed

**"Re-measured cache threshold on the real embedder"** — the *method* half is closed; the
*number* half is not. `text-embedding-004` needs an API key, and CI runs in replay with no
key and no spend, so the vectors come from the local embedder. It is dimension-matched to
production and exercises the whole path, but a lexical embedder scores paraphrases that
share **words** while a semantic one scores paraphrases that share **meaning** — and those
disagree precisely on the cases a threshold has to separate.

`AAKAR_CACHE_THRESHOLD` exists so the real measurement lands as config, not a code change.

### Found while building

- **Qdrant's `delete_collection` leaves its data directory** under a Windows bind mount, so
  the next `create_collection` fails with "data already exists". The test fixture now clears
  *points* rather than the collection — which is also what production does, since it never
  drops the collection.
- **`qdrant-client` resolved to 1.19 against a 1.12 server**, which the client warns about
  on every call. Pinned to `>=1.12,<1.13` to match the image in `docker-compose.yml`.
- **Whole-word matching means "irises" does not match the term "iris".** That is the right
  trade — substring matching fires on "irishman", and a part promoted to `strong` by a
  coincidental prefix is the fabricated-confidence failure D-030 exists to prevent. Inflected
  forms are reached through aliases, which is the designed mechanism (D5). My first test
  asserted the opposite and was wrong.

### Carried forward

- The threshold number, pending a real embedder.
- The relevance floor (0.35) is calibrated against the same local embedder and needs the
  same re-measurement.
- Summary cards and suggested questions (D4) are not built; `/ask` answers free-form
  questions only.
- The answer tier currently stitches retrieved chunks rather than calling a model —
  `generate` is injected, and no prompt is written yet.

---

## D-043 correction · 2026-08-30 (pre-2D, blocking)

The architect flagged one dead model pin. **Checking every one, as instructed, found two.**

| setting | was | status | now |
| --- | --- | --- | --- |
| `AAKAR_EMBED_MODEL` | `text-embedding-004` | shut down **2026-01-14** | `gemini-embedding-001` |
| `AAKAR_MODEL` | `gemini-2.0-flash` | shut down **2026-06-01** | `gemini-3.6-flash` |
| `AAKAR_VLM_MODEL` | `gemini-2.0-flash` | shut down **2026-06-01** | `gemini-3.6-flash` |

Every model this project would ever have called was retired. The embedding model had been
dead seven months when I pinned it; the generation model, three.

**MRL normalization — answered from the docs, and it is a real trap.**
`gemini-embedding-001` does **not** normalize below its native 3072 dimensions; the docs
say the caller must L2 normalize. Cosine on an unnormalized vector does not fail, it just
returns the wrong number — retrieval degrades, the floor starts refusing covered questions,
and every symptom points at a weak embedder. Implemented **unconditionally**, so there is no
model branch to get wrong later. `gemini-embedding-2` auto-normalizes but is `-preview`,
which is the wrong thing behind a one-way door.

**Boot check (D-045), in two layers.** A local retirement registry checked inside
`Settings.from_env()` — no network, runs in every mode, and is the layer that catches what
actually happened; plus a live provider check for `live`/`record`. Evidence in
`evidence/phase2c/model-pin-audit.txt`.

**The pattern, recorded because it will recur.** Pinning protects against *drift*. It does
nothing about a pin to something that no longer exists, and inside a replay-mode suite the
two are identical — both green. I reasoned carefully about dimensionality being a one-way
door without ever checking the door led anywhere.

Also recorded, not built: **D-046**, alias coverage is load-bearing for provenance, and
Phase 3 must verify it against the chapter's actual inflections.

---

## Phase 2D.1 · 2026-09-01 — evals with no key

Everything below ran on the **local lexical embedder** against a **PROPOSED, unverified**
golden set. The method is closed. **Every number is PROVISIONAL.** No API key was obtained
and none was needed; 2D.2 is where the numbers become real.

### a. Golden provenance set — `evals/golden-provenance/`

One real chapter: OpenStax *Anatomy and Physiology 2e* §14.1, CC BY, quotable in full
(D-005). 10 verbatim chunks, one (`c06`) marked `source: "ocr"` so D-044's display path is
exercised by a real question rather than only by a hand-built fixture. 15 questions — 6
single-chunk, 4 multi-chunk, 5 `not_in_chapter`.

The negatives are deliberately hard: each names a part the chapter really discusses and
asks something it never says. `q15` asks the sclera's thickness in millimetres, and the
chapter names the sclera without ever measuring it. A negative that names something absent
is easy and proves nothing.

**Labels are PROPOSED and the code says so** — see D-048. `verified: false`,
`verified_by: null`. Verifying them is a manual pass over `questions.json`.

### b. Answer prompt with inline markers — `aakar/rag/answer.py`

The model emits `[1]`, `[2,3]` — indices into the passage list it was given, never page
numbers. The marker-to-page-label mapping happens in code afterwards. **This is what makes
the eval possible:** a hallucinated page number is indistinguishable from a real one, so an
eval could only ask "is this a plausible page", which is not a question with an answer. A
marker points at a specific retrieved chunk, so "does chunk 2 support this sentence" is
decidable by reading chunk 2. Every rule in the prompt has a corresponding count in the
eval; a rule the eval cannot measure is a wish.

### c. Citation faithfulness — `aakar/evals/faithfulness.py`

Three counts, never a score. Run over 8 hand-written answer fixtures:

| | count |
| --- | --- |
| claims made | 10 |
| supported | 6 |
| **1. markers naming no retrieved passage** | **1** |
| **2. sentences the cited chunk does not support** | **2** |
| **3. uncited claims in no retrieved chunk** | **1** |
| (uncited but present in a chunk) | 1 |
| (lexically ambiguous, needs a human) | 0 |

Those counts are the harness catching fixtures **built to be caught** (R2) — not a
measurement of any model. `missing_markers` is reported beside count 3 and deliberately not
inside it: a true claim with no marker is a prompt problem, a claim from nowhere is a
grounding problem, and one number for both hides which you have.

`supports()` is lexical and reported as a **lower bound**. It over-reports support for a
paraphrase and under-reports nothing, so a non-zero count 2 is a real finding and a zero one
is a floor, not a proof. An LLM judge would be more sensitive and would also be the thing
under test judging itself. Where the lexical check is ambiguous the harness escalates
(`needs_human`) rather than guessing in the direction that flatters the run.

### d. Threshold harness parameterised by embedder — `aakar/evals/{embedders,thresholds}.py`

`AAKAR_EVAL_EMBEDDER` selects a named embedder; each carries whether it may certify a
threshold at all. `local` is `calibrating=False` with its caveat printed alongside every
number it produces. `gemini` is registered and **raises `NotImplementedError` naming 2D.2**
rather than falling back to `local` — a silent fallback would let every harness keep
printing numbers while measuring the stub, which is the exact confusion the 2D.1/2D.2 split
exists to prevent.

Relevance floor sweep over the golden set, on the local embedder — **PROVISIONAL**:

| floor | false coverage | coverage | verdict |
| --- | --- | --- | --- |
| 0.15 | 5 | 100% | UNSAFE |
| 0.25 | 3 | 100% | UNSAFE |
| **0.35 (shipped default)** | **2** | 100% | **UNSAFE on this embedder** |
| 0.45 | 0 | 80% | usable |
| 0.55 | 0 | 70% | usable |
| 0.65 | 0 | 20% | usable |

False coverage is binding and absolute, not a rate — the same rule as the cache threshold.
An uncovered question that clears the floor produces a fluent, cited, wrong answer; one that
should clear and does not produces a true statement the student can act on. Those are not
symmetric, so nothing is optimised across them.

**The shipped `DEFAULT_FLOOR` of 0.35 admits 2 false coverages here.** That is a fact about
word overlap, not about the product — it is exactly the number D-041 says cannot be
transferred from a lexical embedder — but it is the first evidence that the default was
picked without measurement, and 2D.2 must re-measure it.

### e. OCR citations surface their confidence — D-047

Two paths where `display_confidence` was computed correctly and the student still could not
see it, plus one where it vanished entirely on a cache hit. All three fixed; see D-047.

### Not done, deliberately

- **No API key, no live call, no spend.** Every pin is still unverified against the
  provider — the D-045 registry catches known retirements, and nothing has resolved a model
  name against a real endpoint. That is 2D.2.
- **Ten Qdrant-backed tests stayed skipped.** The Docker daemon was not reachable this
  session. The `ask()` changes are covered without it — the cache branch returns before
  retrieval, so the two new cached-answer tests exercise the real code path — but the
  indexed end-to-end `/ask` tests were not re-run.
- **The golden labels have not been verified by a human.** That is the next manual step and
  no number above counts until it happens.

---

## Post-2D.1 corrections · 2026-09-01 (four architect items)

### 1. D-049 — fresh/cached equivalence as a property, and what it found

Generalised the `display_confidence` drop into an invariant driven by the field list, with
the exemptions inverted so a field added later is compared by default.

It diverged on the first run, on four fields — **including `display_confidence`, the one
D-047 had just claimed to fix.** D-047 stored `strength` and re-derived `source` from the
cached citations. The fresh path does not derive `source` from the citations; it reads it
from the chunks that *name the part*, a strict subset. So the reconstruction produced
`strong (partly OCR)` where the fresh answer said `strong (OCR)` — plausible,
self-consistent, and a different value. `naming_chunk_ids` and `retrieved_chunk_ids` were
lost outright; nothing reads them today, the curation gate will.

**I reported that field as fixed at the 2D.1 gate. It was not.** The per-instance fix was
reasoned about correctly and rested on a false premise, and only the property caught it.

Fix: store the whole provenance in one payload, validate both enums on the way back out.
Now covered by three Qdrant-backed tests — the equivalence itself, an R2 test that strips
the stored provenance and requires the comparison to fail, and one asserting a
`not_in_chapter` refusal is reproducible rather than restored (it is never cached).

### 2. D-050 — DEFAULT_FLOOR 0.35 → 0.45, interim and uncertified

The finding is that **0.35 was never measured** — picked by judgement in 2C.3 and shipped as
though calibrated. It admits 2 of 5 hard negatives on the golden chapter. 0.45 is the lowest
swept value admitting none.

Cost, stated: golden-set coverage 100% → 80% (`q04`, `q08` stop clearing). On the
five-sentence `test_retrieval` fixture the cost is total — a directly-covered question
scores ~0.43 there, so three `/ask` tests now pin the floor via `AAKAR_RELEVANCE_FLOOR` with
the reason written down. The shipped default is still exercised on a real chapter by
`test_the_shipped_default_floor_both_admits_and_refuses`, which requires both halves: a
floor at 1.0 refuses everything and would otherwise pass every safety test written about it.

### 3. Qdrant gap closed — and it was not an environment blocker

Docker Desktop was installed and the CLI present; the **daemon was simply not running**.
Started it, brought up Qdrant, and the ten previously skipped tests pass.

**788 passed, 0 skipped.** Not a standing blocker: a machine-state problem I should have
resolved rather than reported around, in Phase 0 and again here. The recurrence was mine,
not the environment's. Bringing the daemon up is now part of running the suite, and it is
what let D-049's tests exist at all — they need a real index.

### 4. Golden set scope limits recorded — and printed

Two `SCOPE_LIMITS` entries in `chapter.json`:

- **A ceiling, not a typical case.** One clean, digital-native, professionally edited
  English OpenStax chapter. The real input is scanned Indian textbooks. Faithfulness here is
  close to the best this system will do; what it establishes is that failures seen on a
  clean chapter are real, since the input cannot be blamed for them.
- **`c06` tests the display path, not OCR noise.** It is clean verbatim text labelled `ocr`.
  It proves the second axis reaches the student; it says nothing about whether real OCR
  artefacts cause citation failures. Future work named in the file: one chunk of real
  Tesseract output over a real scanned page, beside the digital text of the same page.

Both are loaded into `GoldenSet.scope_limits` and printed by the runner on every run — a
caveat that has to be looked up is a caveat that will not be. A test asserts both are
present in the file and reach the report.

### Verification

788 pytest (0 skipped), 439 vitest, ruff + mypy-strict + tsc clean. Evidence regenerated in
`evidence/phase2d/`.

### Still open

2D.2 is not started, per instruction: the golden labels are still unverified, and no pin has
been resolved against a live provider.
