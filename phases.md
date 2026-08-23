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
- **0.7 Owner session (D-011).** API-side session: `pyjwt` HS256 over `AAKAR_AUTH_SECRET`, owner credential hashed with `passlib[argon2]`; `require_owner` FastAPI dependency; `/auth/login`, `/auth/logout`, `/auth/me`. No web auth library. The login *page* lands in Phase 2 with the upload flow, which is where a session first has something to protect.
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
- **1.5 Golden specs (the point of this phase).** Hand-write `specs/golden/human_eye.json`, `earth_layers.json`, `animal_cell.json`. Agent drafts; Shivam tunes visually in the running viewer. Every part carries placeholder-free names/aliases. Provenance uses the reserved `chunk_ids: ["golden"]` sentinel — **Phase 2 task 2.9 backfills real chunk ids** once the corpus is ingested (D-003).
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

## Phase 2 — Ingestion + spatial RAG on golden specs · ≈ 2–3 sessions

**Objective:** click-a-part → page-cited answers from an uploaded chapter, with the cache economics proven — all before generation exists.

### Tasks
- **2.1 Ingestion.** Owner login page + upload endpoint (`require_owner`, D-011) → private storage → `documents` / `corpora` rows; **LightningParse** pipeline → page-numbered, heading-aware chunks; any parser failure captured as a minimal repro in `lightningparse-issues/` with a logged fallback path. Test corpus: an openly licensed text (e.g., OpenStax biology chapters matching the golden topics).
- **2.2 Indexing.** Qdrant `chunks` collection (payload: corpus_id, topic, page, section) + `qa_cache` collection; embedding pipeline through the provider abstraction.
- **2.3 Part-scoped hybrid retrieval (D5).** In-process BM25 over the topic's chunks + dense search, merged via RRF; scope = part name + aliases; thin-results floor (config) triggers widening to chapter scope with the "your chapter covers this under…" notice.
- **2.4 Summary cards + suggested questions (D4).** Generated once per (corpus, topic, part), cached in SQLite; 3–5 sentences, every sentence page-cited.
- **2.5 Chat endpoint.** Semantic cache front, scoped **`(corpus_id, topic, part)`** (D-007), cosine ≥ 0.92 default → on miss: retrieve → generate with `[p. N]` citation contract → cache. "Not in your chapter" state + clearly labeled general-knowledge fallback (Rule 6).
- **2.6 Panel UI.** Summary, suggested questions (tap-to-ask), chat — wired into the viewer's selection state.
- **2.7 Cache benchmark harness.** Scripted 50-question paraphrase set replayed against one topic → hit-rate table. **Plus a near-miss set** of lexically close but semantically distinct questions that *should* miss → false-hit count; the 0.92 threshold is calibrated against both numbers, not accepted as given (G-03).
- **2.8 Tests.** Alias matching; widening trigger; cache hit/miss around threshold; scope isolation between parts and topics; **cross-corpus cache isolation** — a question answered against corpus A never returns a cached hit for the same question against corpus B (D-007); citation-integrity structural test (every response sentence maps to a retrieved chunk with a page).
- **2.9 Golden provenance backfill (D-003).** Replace `["golden"]` in `specs/golden/*.json` with real chunk ids from the ingested corpus. Boundary test: no spec outside `specs/golden/` may use the sentinel.
- **2.10 Citation accuracy check (G-02).** Hand-verify ~20 citations from the Phase 2 transcripts against the source PDF — does the cited page actually support the sentence? The structural test in 2.8 proves only that a page number is present. This is the evidence behind headline claim #2.

### Acceptance gate
- [ ] 6 Q&A transcripts across 2 topics with visible page citations
- [ ] One honest "not in your chapter" transcript
- [ ] Hit-rate table > 60% on the paraphrase set
- [ ] False-hit count on the near-miss set, with the calibrated threshold (G-03)
- [ ] Citation accuracy rate over ~20 hand-verified citations (G-02)
- [ ] Cross-corpus cache isolation test green (D-007)
- [ ] Golden specs carry real chunk ids; sentinel boundary test green (D-003)
- [ ] Cost report pasted
**Evidence to paste:** transcripts, hit-rate + false-hit tables, citation-accuracy worksheet, `pytest` output.

---

## Phase 3 — Governed generation · ≈ 2–3 sessions

**Objective:** the pipeline that turns a chapter into an approved SceneSpec — with the model proposing and humans publishing.

### Tasks
- **3.1 Checklist extractor (D2).** From the topic's chunks → the list of structures the chapter actually teaches; written to a human-reviewable file per topic.
- **3.2 SceneSpec generation.** Prompt = schema + one golden spec as few-shot + the checklist + retrieved structural passages; strict parse into the pydantic model; parse failure → one repair → park.
- **3.3 Validator (D2).** Deterministic: schema, refs/cycles, bounds, `chunk_ids` exist; completeness vs checklist; **evidence check (D-008)** — each part's `provenance.evidence` is matched against the text of its cited chunks (normalized substring, falling back to embedding similarity above a calibrated threshold); a mismatch flags the part ungrounded and feeds the repair prompt. Remaining groundedness signal flagged for the critic.
- **3.4 Critic loop (D3).** Playwright screenshots (2 angles) → VLM critic (checklist + spec + screenshots + optional user figure) → structured critique `{missing_parts, extra_parts, layout_issues, severity}` → repair prompt. Max 2 rounds → `needs_human` with critique attached. **Every attempt's spec + screenshots + critique stored** in `spec_versions`.
- **3.5 Review UI.** Admin route behind the owner session (D-011): pending topics, spec JSON viewer, screenshots, critique, approve / reject → status flip → approved specs appear in the viewer.
- **3.6 Pilot batch.** Runner over 5 topics (eye, cell, neuron, Earth layers, simplified heart) against the open corpus; **budget preflight printed before the batch**; results table generator (checklist size, completeness %, repair rounds, final status, cost). **Run the batch twice — once with the critic disabled (G-04)** — and compare completeness % and final status. Cheap in replay. A null result is a real finding and gets reported as one.
- **3.7 Replay stability.** One full generation recorded, then replayed — identical artifacts.
- **3.8 Retrieval re-validation on generated vocabulary (G-06).** Re-run the Phase 2 retrieval, alias-matching and widening tests against at least one *generated* topic. Phase 2 proved retrieval against hand-tuned part names; generated aliases are where quality is likely to be worst.

### Acceptance gate
- [ ] Pilot results table pasted for all 5 topics
- [ ] Critic-ablation comparison pasted — with vs without the critic (G-04)
- [ ] Review UI screenshots; Shivam's approve/reject decision recorded per topic
- [ ] Retrieval re-validation green on a generated topic (G-06)
- [ ] Replay-stability check passes
- [ ] Batch cost report pasted
**Evidence to paste:** the tables, screenshots list, cost report, `pytest` output.

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
