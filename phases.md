# AAKAR — phases.md
### Detailed execution roadmap · pairs with `aakar-claude-code-prompt.md`

The spec's rules (LLM never emits viewer code, provenance mandatory, human approval gate, cassette) and design decisions D1–D8 govern everything here. This file details *execution order and task-level definition-of-done*. On any conflict, the spec wins — flag it in `DECISIONS.md`.

Effort markers are rough Claude Code sessions, not promises. **Gates end phases, not estimates.**

**Amended 2026-08-23** to fold in the architect's rulings on the pre-Phase-0 review. Decisions D-001…D-013 live in `DECISIONS.md`; open items G-01…G-12 in `GAPS.md`. Tasks and gate items added by those rulings are tagged with the decision or gap they close, so each gate is self-contained.

---

## Phase 0 — Scaffold + schema + codegen · ≈ 1–2 sessions

**Objective:** the monorepo boots and the SceneSpec schema is the enforced single source of truth on both stacks.

### Tasks
- **0.0 Commit the governing documents.** `aakar-claude-code-prompt.md` and `phases.md` at the repo root. DoD: `DECISIONS.md` can be diffed against the text it interprets.
- **0.1 Monorepo.** `apps/web` (Next.js App Router, TS), `services/api` (Python 3.12, FastAPI, `uv`), `packages/scenespec`; a `Makefile` orchestrating both stacks (`make dev`, `make test`, `make codegen`). Web dev deps include **`fast-check`** (D-001). Makefile installs the **Playwright browser** the Phase 3 critic needs (D-009) — the dependency lands now, not in Phase 3.
- **0.2 Docker Compose.** Qdrant only, with healthcheck.
- **0.3 SceneSpec schema.** Author `scenespec.schema.json` v1 exactly per spec §4: geometry vocabulary, transform/material/provenance fields, hard constraints (≤ 40 parts, unique ids, valid parents, numeric bounds). `"golden"` is a reserved `chunk_ids` value (D-003).
- **0.4 Codegen + drift test (D7).** Schema → zod (web) and pydantic (api); `make codegen`; CI drift test = regenerate + `git diff --exit-code`. DoD: editing the schema without regen fails CI (demonstrate, then revert).
- **0.5 SQLite bookkeeping.** `users`, `documents`, `corpora`, `topics`, `spec_versions` (spec JSON + status: draft / needs_human / approved / rejected), `approvals`, `llm_calls`, `qa_cache_meta`. **Every user-scoped table carries `owner_id`** even though v1 has one owner (D-011) — vNext multi-user is then a policy change, not a migration. Seed the single owner row.
- **0.6 Provider abstraction + cassette + cost log.** House pattern, ported: chat, VLM, embeddings behind one interface; `live | record | replay`; VLM cassette keys include screenshot hashes; `AAKAR_MAX_USD_PER_RUN` kill-switch scaffolding.
- **0.7 Owner session (D-011).** API-side session: `pyjwt` HS256 over `AAKAR_AUTH_SECRET`, owner credential hashed with `passlib[argon2]`; `require_owner` FastAPI dependency; `/auth/login`, `/auth/logout`, `/auth/me`. No web auth library. The login *page* lands in Phase 2A with the upload flow, which is where a session first has something to protect.
- **0.8 CI both stacks.** ruff + mypy + pytest; eslint + tsc + vitest; drift check; Playwright browser install.

### Out of scope this phase
Any rendering, any retrieval, any generation prompts. Multi-user auth (vNext, D-011).

### Acceptance gate
- [ ] Both test suites green (paste both)
- [ ] Drift-test failure demo captured, then reverted
- [ ] Schema tables exist with `owner_id` on every user-scoped table (paste `.schema`) (D-011)
- [ ] Owner login succeeds; an unauthenticated call to a `require_owner` route returns 401 (paste both) (D-011)
**Evidence to paste:** `pytest` + `vitest` output; the failing-then-passing drift CI runs; SQLite schema dump; auth transcript.
**Then stop** and report per spec §10.

---

## Phase 1 — Compiler + viewer, zero LLM · ≈ 2–3 sessions

**Objective:** hand-written specs render as polished, clickable 3D — proving the schema is expressive enough before any model touches it.

### Tasks
- **1.1 Compiler.** `packages` or web-local module: schema-valid spec → three.js object graph. One builder per geometry type (sphere, box, cylinder, cone, torus, capsule, tube, lathe, extrude); transform + parent resolution (reject cycles); material mapping. Validation errors must be actionable ("part `lens`: lathe profile needs ≥ 3 points").
- **1.2 Viewer route.** `/render/[topic]`: R3F canvas, orbit/touch controls (drei), raycast click → selected part id, hover outline, label billboards with toggle. Route resolves the **approved** spec by default; `?spec_version={id}` selects any version and is gated on the owner session (D-004).
- **1.3 Cutaway.** Clipping plane from the spec; `clip_exempt` honored; UI toggle. DoD: Earth-layers spec shows a clean cross-section.
- **1.4 Exploded view.** Radial vectors from assembly centroid, slider-controlled; deterministic, no schema field. **Decide and log (G-10):** does explosion move top-level parts only, carrying children with them, or every part independently? Visual call, made in the running viewer.
- **1.5 Golden specs (the point of this phase).** Hand-write `specs/golden/human_eye.json`, `earth_layers.json`, `animal_cell.json`. Agent drafts; Shivam tunes visually in the running viewer. Every part carries placeholder-free names/aliases. Provenance uses the reserved `chunk_ids: ["golden"]` sentinel — **Phase 2B task 2B.11 backfills real chunk ids** once the corpus is ingested (D-003).
- **1.6 Screenshot harness.** Playwright against `/render/[topic]?angle=n&shot=1` → PNGs. Written as a thin CLI over the same code path the Phase 3 critic drives (D-009), so gate captures and critic captures cannot drift apart.
- **1.7 Tests.** vitest unit tests per geometry builder; **property-test-generated** fuzz via `fast-check` over schema-valid specs (D-001) — the compiler must be total (never crash on valid input); rejection tests per constraint violation.

### Out of scope this phase
Any LLM call; the info panel; ingestion.

### Acceptance gate
- [ ] All 3 golden topics render; screenshots ×2 angles each in `evidence/phase1/`
- [ ] Cutaway + exploded captures for Earth layers
- [ ] Fuzz + rejection tests green; `llm_calls` count = 0 (assert)
- [ ] Final `schema_version` stated — the schema has stopped moving (D-010)
- [ ] Exploded-view hierarchy ruling logged in `DECISIONS.md` (G-10)
**Evidence to paste:** test output; screenshot file list; one short screen-capture note of click/hover working.

---

## Phase 2A — Ingestion, corpus addressing, ingest limits · ≈ 2 sessions

**Amended 2026-08-26.** Phase 2 as originally written was "ingestion + spatial RAG" and carried too much for one gate. It is split: **2A** is ingestion, corpus addressing and ingest limits; **2B** is spatial RAG, caching, spend controls and degraded mode. Separate gates, separate reports. **2B does not start until 2A is approved.**

**Objective:** an uploaded chapter becomes addressable, page-numbered, deduplicated content — with the ingest boundary hardened before anything is built on top of it.

### Ruling: corpus ownership (settled — implement as stated)

Content-hash dedupe requires shared corpora; D-011 puts `owner_id` on `corpora`. Those are incompatible. Resolution:

- **`documents` stays owned** — `owner_id NOT NULL`. It is the upload record.
- **`corpora` becomes ownerless and content-addressed**, keyed by a hash of the raw file bytes. It holds parsed content and embeddings. `owner_id` is dropped.
- **New `corpus_grants`** (`owner_id`, `corpus_id`, `granted_at`). Access is by grant, never by ownership.
- **`qa_cache_meta.corpus_id` stays NOT NULL.** D-007 holds; the cache is shared by design.

Consequences to implement rather than discover:

- The owner-scoping assertion becomes **"owner A cannot read a corpus they hold no grant for."** The seven-table registry test changes: `corpora` leaves it, `corpus_grants` joins it.
- **Byte-identical files dedupe; nothing else does.** A private document has a unique hash and is structurally isolated with no special-casing. This goes in `DECISIONS.md` — shared caching sounds alarming until it is shown to be impossible across non-identical content.

### Tasks
- **2A.1 Wire `CostLedger` into `CassetteProvider` — first, before any other 2A work.** `test_the_guard_is_not_wired_into_the_provider` must fail once the wiring lands. Report both states.
- **2A.2 Content-addressed corpora** per the ruling above, migration included.
- **2A.3 Ingest hard limits**, enforced at the upload boundary and rejecting *before any work begins*: max file size, max page count, max OCR-eligible pages per document, per-owner ingest quota (documents/day, pages/day). Rationale, so the numbers are not arbitrary: LightningParse OCR runs on the order of **25 s/page**, so a 400-page scan is roughly **three CPU-hours for one upload with no LLM call** — no budget guard fires. This is a denial-of-service surface, not a cost surface. Propose numbers with reasoning for approval. Rejection is explicit at upload, **never a silent queue**.
- **2A.4 Encrypted / unparseable PDFs** — clean explicit rejection with an actionable reason. Not a crash, not a silent OCR fallback.
- **2A.5 Per-chunk warning capture.** LightningParse emits a warnings array; capture and store it at the finest granularity available, because provenance strength in the UI derives from it. Report whether warnings are per-chunk or per-document today; if per-document only, store at that granularity, **note the limitation, and do not fake resolution**. Do not modify LightningParse from this repo.
- **2A.6 Page label vs page index** — stored as **two separate fields, always**. They diverge with front matter and restarting chapter numbering. Citations render the *label*; internal addressing uses the *index*. Never conflate, never infer one from the other.
- **2A.7 Qdrant healthcheck** — carried unverified from Phase 0. 2A is the first phase that needs a running Qdrant. Verify against the real image and paste the output.

### Acceptance gate
- [ ] Two owners upload byte-identical files → **one corpus row, two document rows, two grants, one embedding cost** in the ledger. Paste the ledger.
- [ ] `CostLedger` wired; the "not wired" test fails. Both states reported.
- [ ] Ingest limits reject oversized and over-length uploads *at the boundary*.
- [ ] Encrypted/unparseable PDF rejected with an actionable reason.
- [ ] Page label and page index stored separately; a document with front matter shows them diverging.
- [ ] Qdrant healthcheck verified against the real image.

**Evidence to paste:** the ledger, rejection transcripts, a label-vs-index sample, healthcheck output, `pytest` output.
**Then stop** and report per spec §10.

---

## Phase 2B — Spatial RAG, caching, spend controls · ≈ 2–3 sessions

**Does not start until 2A is approved.**

**Objective:** click-a-part → page-cited answers from the uploaded chapter, with the cache economics measured and the spend surfaces closed.

### Tasks
- **2B.1 Part-scoped hybrid retrieval (D5).** In-process BM25 over the topic's chunks + dense search, merged via RRF; scope = part name + aliases, **or `instance_of` when present (D-022)**. Thin-results floor (config) triggers widening to chapter scope with the "your chapter covers this under…" notice.
- **2B.2 Summary cards + suggested questions (D4).** Generated once per (corpus, topic, part scope), cached in SQLite; 3–5 sentences, every sentence page-cited.
- **2B.3 Model tiering.** Two configured tiers: a **generation tier** (SceneSpec emission, VLM critic — frontier model, used in Phase 3) and an **answer tier** (QA from retrieved chunks — small model). Generation is once-per-topic-forever and amortises across all users; QA is per-user-per-question and never stops. **Only QA scales.** Tiers are configurable per call site and recorded in the cost ledger **by tier**, so the split is measurable.
- **2B.4 Semantic QA cache.** Keyed on `(corpus_id, part scope, question embedding)`; hit above a similarity threshold within the same corpus and part scope. **`instance_of` interaction:** parts sharing an `instance_of` are one retrieval target and therefore **one cache scope** — two mitochondria share cached answers. Report the threshold and how it was chosen; a permissive threshold buys hit rate by answering questions the student did not ask, so **correctness is the binding constraint, not hit rate**.
- **2B.5 Per-owner quota.** The budget preflight is global — one user in a loop drains it for everyone. Add a per-owner **daily question quota** at the same call site. Global budget and per-owner quota are **separate checks; both must pass**.
- **2B.6 Degraded mode.** When the budget is exhausted or the provider is unavailable, **do not 500**. Generation and uploads disable; the approved-topic library and all cached answers keep serving, since they cost nothing. Clear banner stating what is unavailable and why. Testable at zero cost in replay with the provider hard-disabled.
- **2B.7 Registration ceiling.** Config flag for maximum total accounts, waitlist beyond it. Default low.
- **2B.8 Panel UI.** Summary, suggested questions (tap-to-ask), chat — wired into the viewer's selection state.
- **2B.9 Cache benchmark harness.** Scripted 50-question paraphrase set replayed against one topic → hit-rate table. **Plus a near-miss set** of lexically close but semantically distinct questions that *should* miss → false-hit count; the threshold is calibrated against both numbers, not accepted as given (G-03).
- **2B.10 Tests.** Alias matching; widening trigger; cache hit/miss around threshold; scope isolation between parts and topics; **cross-corpus cache isolation** (D-007); citation-integrity structural test.
- **2B.11 Golden provenance backfill (D-003).** Replace `["golden"]` in `specs/golden/*.json` with real chunk ids. Boundary test: no spec outside `specs/golden/` uses the sentinel.
- **2B.12 Citation accuracy check (G-02).** Hand-verify ~20 citations from the transcripts against the source PDF. This is the evidence behind headline claim #2.

### Acceptance gate
- [ ] **Cache hit rate measured across two owners on the same corpus** asking equivalent questions — measured, not asserted
- [ ] Cost ledger shows the **tier split by call site**
- [ ] **Per-owner quota refuses at the limit while a second owner is unaffected**
- [ ] **Full app functional with the provider hard-disabled**: library browsable, cached answers served, generation and upload cleanly refused
- [ ] Ingest limits reject oversized and over-length uploads at the boundary
- [ ] 6 Q&A transcripts across 2 topics with visible page citations; one honest "not in your chapter" transcript
- [ ] Hit-rate table > 60% on the paraphrase set, **with** the near-miss false-hit count and the calibrated threshold (G-03)
- [ ] Citation accuracy rate over ~20 hand-verified citations (G-02)
- [ ] Cross-corpus cache isolation test green (D-007)
- [ ] Golden specs carry real chunk ids; sentinel boundary test green (D-003)
- [ ] Cost report pasted

**Evidence to paste:** transcripts, hit-rate + false-hit tables, citation-accuracy worksheet, ledger tier split, quota and degraded-mode transcripts, `pytest` output.

### Not in scope (2A or 2B)
**No billing, no payment integration, no checkout.** Metering and protection only. The end deliverable is a **cost model in the README** — per-topic and per-question breakdown, measured hit rate, projected monthly cost at a stated MAU — not a paywall.


## Phase 3 — Governed generation · split 3A / 3B / 3C · architect scope 2026-09-01

**Objective:** the pipeline that turns a chapter into an approved SceneSpec — with the model proposing and humans publishing.

**Superseded structure.** The original 3.1–3.8 task list is replaced by three sub-phases with separate gates, each blocked on the previous. Phase 2 needed splitting three times; this one is larger. The original items map as follows: 3.1 → 3A; 3.2, 3.3 → 3B; 3.4, 3.7 → 3C; 3.5 (review UI) → **Phase 4**, out of scope here; 3.6 pilot batch and 3.8 retrieval re-validation → folded into the 3B/3C gates.

**Standing constraint.** Every measured number in this phase is certified against `gemini-3.6-flash` and the golden set at `ecf6954`, the same way D-058 is certified against `gemini-embedding-001`. The model and set commit are recorded alongside each figure. A model change invalidates them.

### 3A — Chapter structure extraction

Prerequisite to everything else, previously invisible in the plan. The curation gate displays "9 structures named in the chapter, 6 present in the spec" — which requires knowing what the chapter names. That is its own extraction task with its own accuracy question, and folding it into generation would leave it unmeasured.

- **3A.1** Extract, from a chapter, the set of named anatomical/structural entities, with the chunk that names each and the page label. Model proposes `(entity, naming_chunk)` pairs; a deterministic verifier confirms each with the same whole-word matcher provenance uses; unconfirmed pairs dropped. Precision by construction, recall measured at the gate.
- **3A.2** Aliases and inflections per entity (D-046, D-063): deterministic inflector for inflections, model synonyms and abbreviation expansions from the same call, a precision guard on model synonyms, and a **global collision check** across the whole alias set regardless of source — a shared surface form is a defect that fails extraction, never a warning.
- **3A.3** Output is the coverage baseline the curation gate reads, with `modellable` per entity (D-064) so 3B can separate "named and omitted" from "named and out of scope".

**Gate**
- [ ] Hand-labelled structure set for the OpenStax chapter in the golden set, verified by the architect (`evals/golden-structures/structures.json`, labels produced by the mechanical rules in D-064)
- [ ] Precision and recall against that set, as counts, not a score
- [ ] Alias coverage reported separately: for each entity, do the emitted aliases cover the inflections that actually appear in the chapter text
- [ ] Cost per chapter, measured
- [ ] Scope limits loaded into the runner and printed on every report

### 3B — Spec generation

- **3B.1** Generate a SceneSpec from a chapter plus the 3A structure set. Constrained emission against the schema.
- **3B.2** Provenance must be honest. `chunk_ids` may be empty (schema 1.2) and the generator must actually use that when the chapter does not assert a part. **Highest-risk item in the phase** — the failure is a model that always finds something to cite because citing is easier than admitting absence.
- **3B.3** Parent relations per D-031: scene-graph only. The derived containment relation comes from `compile()`. The generator does not assert semantics.
- **3B.note — coextensive pairs (architect, 2026-09-02; recorded, not acted on).** *anterior cavity / aqueous humor* and *posterior cavity / vitreous humor* are near-coextensive. A spec carrying both members of a pair gives the containment classifier two parts in the same volume — not contained, not surrounding, not surface-attached. Expect it; do not discover it as an unexplained warning.
- **3B.4** Model selection, measured, not inherited. `gemini-3.6-flash` is the provider's replacement for a retired pin, never a choice for this workload. Measure schema-valid-on-first-attempt rate, referential-valid rate, and cost per topic. If flash cannot hold the schema, report it and propose the escalation rather than silently retrying.

**Gate**
- [ ] Generate `human_eye` from the chapter and compare against the hand-written golden spec — not exact match, but: structures present in golden and absent in generated, and vice versa; depth and parent-graph shape; geometry type distribution
- [ ] **Zero-provenance parts must actually occur.** Construct a case where the chapter is silent about a structure the model would plausibly include, and show the generator emits empty `chunk_ids` rather than citing the nearest chunk. If they never occur across all three topics, that is a finding, not a pass — report it and stop
- [ ] Schema-valid and referential-valid rates over at least 10 generations
- [ ] Cost per topic, measured, with the repair budget not yet in play

### 3C — VLM critic and repair loop

- **3C.1** Critic reads the **unlabeled** capture (item 7, D-007 split). Labels are the curator's input, not the critic's, or the loop spends its budget on cosmetics.
- **3C.2** Critic also reads the derived relation and any compile warnings riding the sentinel (D-040). A render failure yields relation plus error, which is a better input than nothing.
- **3C.3** Up to 2 repair rounds, budget enforced and recorded per topic in the ledger.
- **3C.4** Verdict, repair history and coverage gaps assembled into what the curation gate will read. The critic never approves — that stays human.

**Gate — the seeded-defect suite is the item that matters.** Take the hand-written golden specs and break each in a known way, one defect per fixture. At minimum: a detached child; a part with a colour contradicting its structure; a transposed label pair; a missing structure the chapter names; a degenerate zero-volume mesh; a part occluding everything else. Require the critic to catch each, and report which it catches and which it misses. Without this, "the critic said it was fine" is unfalsifiable — R2 applied to the critic, and the only thing standing between a generated library and a plausible wrong one.
- [ ] Seeded-defect suite: catches and misses, per defect
- [ ] False positives: the critic run on the three unmodified golden specs — every finding is a false positive. A critic noisy on correct input gets ignored, same argument as the containment warnings
- [ ] Do repair rounds improve the render, measured against the seeded defects, or do they churn
- [ ] Cost per topic including repairs

### Not in scope for Phase 3
The curation gate UI. Phase 3 produces the data it reads; the interface is Phase 4.

---

## Phase 3.5 — Geometry vocabulary and scene presentation · architect scope 2026-09-01

**Rationale.** The nine primitive types produce assemblies that read as nested spheres. This is a product-quality ceiling, not a correctness bug — every render is valid and none of them look like a textbook figure. The fix is a richer **parametric** vocabulary, not imported meshes: imports would return the segment-and-label problem the SceneSpec approach exists to avoid, and would break provenance and coverage entirely (see the DECISIONS entry on rejected asset-library sourcing).

**Ordering constraint.** Must complete **before any topic is approved into the shared library**. Regenerating specs is cheap; re-curating approved topics by hand is not. May run before or after 3B/3C, but never after curation begins.

- **3.5.1 Lathe / surface of revolution.** A 2D profile curve rotated about an axis. Covers eyeball, cornea, lens, soma, tooth, bone shaft, most organs. The single highest-value addition. Schema: profile as a bounded point list, axis, sweep angle, segment count. Deterministic compiler builder, as with existing types. Must participate in cutaway (clip plane) and explode identically to other types. Containment classification must handle it — the analytic inside-test needs a polygon-winding approach, not a primitive formula.
- **3.5.2 Sweep / tube along curve.** A profile swept along a spline path. Covers axon with bends, blood vessels, nerve tracts, digestive tract, ducts. Schema: path control points, radius (constant or per-point), segments. Same cutaway/explode/containment requirements.
- **3.5.3 Scene presentation.** Currently default lighting. Establish a deliberate setup — key/fill/rim or equivalent — consistent across all topics so the library reads as one product rather than forty. Verify against both label variants (D-007 capture split): the critic's unlabeled capture must stay legible under the new lighting.

**Gate**
- [ ] Schema bump, both stacks, conformance fixtures for both new types including the behavioural axis (defaults present and absent)
- [ ] One existing golden spec rebuilt using the new types, rendered side by side with the primitive version
- [ ] Cutaway, explode, containment classification and label placement all verified on the new types — the 40-part stress fixture regenerated to include them
- [ ] Critic false-positive rate re-checked: new geometry must not make correct specs look wrong

---

## Phase 4 — Library + polish · ≈ 1–2 sessions

**Objective:** the product loop end-to-end, presentable.

### Tasks
- **4.1 Library page.** Approved topics grid; per-topic shareable **read-only** viewer route. **Share links pin a `spec_version`** (D-013) — a revision does not silently change what a reader sees.
- **4.2 Upload flow hardening.** Owner-only upload, file-type/size validation, friendly failures. Authorization checks on every private resource: PDFs, chunks, draft specs, cached answers.
- **4.3 Mobile QA.** Touch orbit/select verified on a real phone; loading/suspense states; error boundaries around the canvas and the panel.
- **4.4 Admin cost meter.** Cumulative + per-topic spend from `llm_calls`.
- **4.5 E2E demo capture.** Upload → generate → review → approve → share link → click parts → cited answers, as numbered screenshots. Uses the **open corpus** (D-005) — nothing committed to `evidence/` comes from a third-party textbook.
- **4.6 Share-link abuse control (D-012, G-12).** Anonymous readers get cached summaries and suggested questions; **free-form chat is disabled on share links**, so an anonymous URL cannot spend money in a loop. If chat is later enabled for share links, it requires a per-link rate limit *and* a hard per-link daily spend cap, both enforced server-side.
- **4.7 Spec revision semantics (D-013).** Revising an approved topic invalidates cached answers and summaries for parts that were renamed or removed; surviving parts keep their cache.

### Acceptance gate
- [ ] Numbered screenshot walkthrough in `evidence/phase4/`
- [ ] No console errors on the viewer route; basic Lighthouse pass
- [ ] **Privacy:** an unauthenticated request fails to fetch owner-private PDFs, chunks, draft specs and cached answers — paste the 403s (G-05)
- [ ] **Abuse:** a scripted anonymous loop against a share link triggers no LLM spend; `llm_calls` delta = 0 (G-12)
- [ ] Share link pins its `spec_version` across a revision; cache invalidation verified for a renamed part (D-013)
**Evidence to paste:** screenshot list, Lighthouse summary, the 403 transcript, abuse-test output.

---

## Phase 5 — Stretch (never blocks the project) · ≈ 2 sessions

**Objective:** universality + the story told well.

### Tasks
- **5.1 2D hotspot tier.** VLM locates labeled regions on the user's *own* uploaded diagram → SVG hotspot overlay → wired to the exact same RAG panel, provenance and caching rules unchanged. This is the fallback for every topic primitives can't express.
- **5.2 README.** Both headline claims linked to evidence; architecture sketch; honest scope statement (schematic topics, not organic surfaces); copyright note (private uploads vs openly licensed public library). **Two required qualifiers:** the cache claim amortizes across readers of a *shared* corpus, not across users with separate uploads (G-08); and the generation results are **N = 5 pilot topics**, stated next to the completeness numbers (G-09).
- **5.3 2-minute demo script.**

### Acceptance gate
- [ ] Hotspot tier demo on one non-3D-able topic (e.g., a labeled flower diagram or circuit figure)
- [ ] README review pass by Shivam, with both qualifiers present (G-08, G-09)
**Evidence:** screenshots + transcript under `evidence/phase5/`.
