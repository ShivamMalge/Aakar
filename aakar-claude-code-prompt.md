# AAKAR — Syllabus-Grounded Interactive 3D Learning Components
## Claude Code Build Prompt · v1.1

> **Aakar** (आकार — form). Upload a chapter or syllabus → an LLM emits a structured **SceneSpec** → a deterministic renderer builds a labeled, clickable 3D model in the browser → clicking any part opens a RAG panel grounded in the student's own material, with page citations, suggested questions, and a part-scoped chat.

You are the implementation engineer for Aakar. Shivam is the architect and reviewer. This document is your complete brief. Read it fully before writing any code.

---

## 1. What Aakar is

The core insight: **we never generate 3D geometry with a diffusion model, and the LLM never writes rendering code.** The LLM's only 3D job is to emit a `SceneSpec` JSON — a declarative description of named parts built from a closed vocabulary of parametric geometry. A deterministic compiler renders it. Every part is therefore *born* labeled and clickable; the unsolved "segment and label a generated mesh" problem is skipped, not solved.

Two headline claims this project must honestly earn:

1. "I built a constrained-generation pipeline: LLM → schema-validated SceneSpec → deterministic renderer → VLM critic → human approval. The model proposes structure; trusted code builds it."
2. "I built spatial RAG: the retrieval scope is the 3D part you clicked, answers come from the student's own uploaded chapter with page citations, and a semantic cache makes marginal cost per user approach zero."

v1 targets **schematic, layered, parametric topics** where primitives shine: human eye, animal/plant cell, neuron, Earth's layers, simplified heart, DNA helix, OSI stack. Realistic organic surfaces (folded cortex) are explicitly out of scope — Aakar builds the 3D equivalent of a textbook figure: stylized but labeled, which beats realistic-but-unlabeled for learning.

---

## 2. Non-negotiable working rules

1. **Operate only inside this repository.** Never read, modify, or delete anything outside it.
2. **Evidence over claims.** A task is done only when you paste real terminal output — pytest results, screenshots (as files in `evidence/`), cache-hit tables, cost reports. Never summarize results you did not produce.
3. **Work phase by phase (0 → 5).** Do not start a phase before the previous gate passes. Stop and report at each gate; wait for approval.
4. **Ambiguity protocol:** pick the simplest option consistent with this spec, log it in `DECISIONS.md`, continue. Ask only when truly blocked.
5. **The LLM never emits executable code for the viewer — only SceneSpec JSON.** No `eval`, no LLM-written JS/GLSL, ever. This is both a determinism rule and the security model.
6. **Provenance is mandatory.** Every SceneSpec part cites the chunk(s) of the user's material that assert it exists. Every Q&A answer cites page/section. If retrieval finds nothing, the answer says so plainly; a general-knowledge fallback must be visibly labeled as *not from your chapter*.
7. **Every LLM/VLM call goes through the provider abstraction** with cost logging and the record/replay cassette (D8). Tests and CI run in `replay` mode.
8. **Human approval gate:** no generated topic enters the library until Shivam approves it in the review UI. The pipeline prepares; he publishes.
9. Maintain `PROGRESS.md` and `DECISIONS.md`.
10. Copyright: user uploads are private, per-user, for personal study. Anything published to a shared/public library must be built only from openly licensed sources — verify before publishing.

---

## 3. Tech stack (pinned — do not substitute)

- **Monorepo:** `apps/web` (Next.js App Router, TypeScript) + `services/api` (Python 3.12, FastAPI, `uv`)
- **3D:** react-three-fiber + @react-three/drei; deterministic SceneSpec compiler in TypeScript
- **Schema:** `packages/scenespec/scenespec.schema.json` is the **single source of truth**; codegen zod types (web) and pydantic models (api) from it in CI — hand-written duplicates are forbidden
- **Ingestion:** LightningParse (Shivam's own library) for PDF → text + page numbers; if a document breaks it, capture a minimal repro in `lightningparse-issues/` and continue with a logged fallback
- **Retrieval:** Qdrant (Docker) — chunks collection + semantic-answer-cache collection; hybrid retrieval (BM25 via a lightweight index + dense)
- **Bookkeeping:** SQLite (`users`, `documents`, `corpora`, `topics`, `spec_versions`, `approvals`, `llm_calls`, `qa_cache_meta`); every user-scoped table carries `owner_id` from day one
- **Auth (single-owner):** the API owns the session — `pyjwt` (HS256, `AAKAR_AUTH_SECRET`) + `passlib[argon2]` for the owner credential; no auth library on the web side. Two principals only: **owner** and **anonymous share-link reader**. Real multi-user auth is vNext (D-011)
- **LLM/VLM/embeddings:** provider abstraction, models from env (`AAKAR_MODEL`, `AAKAR_VLM_MODEL`, `AAKAR_EMBED_MODEL`); Gemini Flash-class defaults
- **Screenshots for the critic loop:** Playwright against the web viewer's `/render/{topic_id}?angle=n` route
- `structlog`, `pytest` + `hypothesis`, `ruff`, `mypy` (strict on `services/api`); `vitest` + `fast-check` for the TypeScript compiler (hypothesis cannot fuzz it in-process — D-001)
- Docker Compose: qdrant only. Keep infra light.

---

## 4. SceneSpec v1 (the heart of the project)

```jsonc
{
  "schema_version": "1.0",
  "topic": "human_eye",
  "title": "The Human Eye",
  "parts": [
    {
      "id": "lens",
      "name": "Lens",
      "aliases": ["crystalline lens"],
      "parent_id": "eyeball",              // optional; must reference an existing id
      "geometry": { "type": "lathe", "profile": [[0,-0.4],[0.55,0],[0,0.4]], "segments": 48 },
      "transform": { "position": [0.6,0,0], "rotation": [0,0,90], "scale": [1,1,0.55] },
      "material": { "color": "#cfe8ff", "opacity": 0.85, "roughness": 0.3 },
      "clip_exempt": false,
      "importance": "core",                 // core | secondary
      "provenance": { "chunk_ids": ["c17","c18"], "evidence": "…the biconvex lens focuses light…" }
    }
  ],
  "cutaway": { "enabled": true, "plane": { "normal": [0,0,1], "constant": 0 } },
  "camera_hint": { "position": [3,2,4], "look_at": [0,0,0] }
}
```

**Geometry vocabulary (closed set):** `sphere{radius}`, `box{w,h,d}`, `cylinder{r_top,r_bottom,height,open_ended?}`, `cone{radius,height}`, `torus{radius,tube}`, `capsule{radius,length}`, `tube{path:[[x,y,z]…], radius, closed?}` (nerves, vessels, helix strands), `lathe{profile:[[x,y]…], segments}` (lenses, vases, eyeball cross-sections), `extrude{shape:[[x,y]…], depth}`. Ellipsoids = sphere + non-uniform scale. **CSG/booleans: out of scope for v1** (log as vNext).

**Hard constraints (schema + validator):** ≤ 40 parts; unique ids; valid parent refs (no cycles); every part carries ≥1 `provenance.chunk_ids` entry; numeric bounds on all params; colors as hex. Reject anything else — the repair loop exists for a reason.

**Viewer behaviors (deterministic, not in the spec):** raycast click → select part; hover outline; label billboards toggle; cutaway toggle using the spec's plane (parts may opt out via `clip_exempt` — e.g., the label anchor); **exploded view** computed radially from the assembly centroid, no schema field needed; keyboard/touch orbit via drei controls.

---

## 5. Core design decisions (do not silently deviate)

**D1 — LLM proposes structure; trusted code builds it.** Same law as Gaon's economy engine. A hallucination can produce a wrong *spec*, which validators and a human catch — it can never produce arbitrary code execution or an unlabeled blob.

**D2 — Two-sided grounding check.** Before generation, an extraction call produces a **structure checklist** from the user's material (the named parts the chapter actually teaches; human-reviewable). The validator then checks the spec both ways: *completeness* (every checklist structure appears as a part) and *groundedness* (every part cites real chunk_ids whose text plausibly mentions it — verify chunk_ids exist; the critic judges plausibility). Fail either → repair round.

**D3 — Governed generation loop.** `extract checklist → generate SceneSpec → schema-validate (deterministic) → render 2 screenshots (Playwright) → VLM critic (checklist + spec + screenshots + optional user textbook figure) → structured critique {missing_parts, extra_parts, layout_issues, severity} → repair prompt`. Max **2 repair rounds**, then park as `needs_human` with the critique attached. Approved or not, every attempt's spec + screenshots + critique are stored — that audit trail is demo material.

**D4 — Generate once per topic; serve forever.** Approved SceneSpecs are static JSON. Per-(topic, part) summaries and suggested questions are generated once and cached. Free-form Q&A goes through a **semantic answer cache**: embed the question, search cache scoped to (topic, part), cosine ≥ threshold (config, default 0.92) → serve cached with a "similar question" note; miss → retrieve → generate → cache. Cost scales with unique questions, not users.

**D5 — Part-scoped retrieval with honest widening.** Retrieval filter = topic + part name/aliases (hybrid BM25 + dense). If top results are thin (score floor in config), widen to chapter scope and say so in the answer ("your chapter covers this under the section on…"). Never silently answer from general knowledge — the fallback exists but is labeled (Rule 6).

**D6 — Page-cited answers.** LightningParse metadata carries page numbers through chunking; every generated claim in the panel cites `[p. N]`. No citation → the sentence doesn't ship.

**D7 — Schema as single source of truth.** JSON Schema → codegen zod + pydantic in CI; a drift test fails the build if generated types are stale.

**D8 — Record/replay cassette.** Modes `live | record | replay`; `hash(canonical_request) → response`, VLM calls included (screenshot hashes in the key). All tests/CI in `replay`. Budget: `AAKAR_MAX_USD_PER_RUN`; print projected cost before any live generation batch; refuse if over.

---

## 6. Spatial RAG panel (what a click delivers)

1. **Summary card** — cached per (topic, part): 3–5 sentences from the user's chapter, page-cited.
2. **Suggested questions** — 3, cached, each tap-to-ask.
3. **Chat** — scoped to the part (D5 widening rules), every answer cited, semantic cache in front (D4).
4. **"Not in your chapter" state** — if the part is only weakly covered, say so and offer the labeled general-knowledge fallback.

---

## 7. Phases & acceptance gates

### Phase 0 — Scaffold + schema + codegen
Monorepo, Docker Compose (qdrant), SceneSpec JSON Schema, zod/pydantic codegen + drift test, SQLite schema, provider abstraction + cassette + cost log, CI (ruff/mypy/pytest + vitest + drift check).
**Gate:** pytest + vitest green (paste both); drift test demonstrably fails when the schema is edited without regen (show it, then revert).

### Phase 1 — Compiler + viewer, zero LLM
Deterministic SceneSpec → three.js compiler; viewer with click/hover/labels/cutaway/exploded view; **3 hand-written golden specs** committed under `specs/golden/`: `human_eye`, `earth_layers`, `animal_cell`. Writing these by hand is the point — it proves the schema is expressive enough before any model touches it. Property tests: compiler is total over schema-valid specs (hypothesis-generated specs never crash it); invalid specs rejected with actionable errors.
**Gate:** screenshots of all 3 golden topics from 2 angles in `evidence/phase1/`; cutaway + exploded demos captured; `llm_calls` table empty (assert it); tests green.

### Phase 2 — Ingestion + spatial RAG on golden specs
LightningParse ingestion (page-numbered chunks → Qdrant), part-scoped hybrid retrieval, summary cards + suggested questions + cited chat, semantic answer cache, honest-widening and not-in-chapter states. Wire to the golden specs using an openly licensed biology text (e.g., OpenStax) as the test corpus.
**Gate:** transcript of 6 Q&As across 2 topics with visible page citations; one honest "not in your chapter" transcript; a scripted 50-question replay run showing the semantic-cache hit rate table (target: >60% on the paraphrase set); cost report.

### Phase 3 — Governed generation
Checklist extraction, SceneSpec generation, validator (D2), Playwright screenshot harness, VLM critic, repair loop (≤2), `needs_human` parking, review UI (admin route: pending topics, screenshots, critique, approve/reject).
**Gate:** run the pipeline on **5 pilot topics** (eye, cell, neuron, Earth layers, simplified heart) against the open corpus; table of results per topic — checklist size, completeness %, repair rounds, final status; all specs + screenshots + critiques stored and visible in review UI; Shivam approves/rejects each personally; cassette-replay of one full generation is byte-stable.

### Phase 4 — Library + polish
Approved-topic library page; per-topic shareable read-only viewer route; upload flow hardened (private per-user storage); mobile touch controls verified; loading states; cost meter in admin.
**Gate:** end-to-end demo script — upload chapter → generate → review → approve → open share link → click parts → cited answers — captured as numbered screenshots in `evidence/phase4/`; Lighthouse pass on the viewer route (no console errors).

### Phase 5 — Stretch (do not gate the project on it)
**2D hotspot tier:** VLM locates labeled regions on the user's own uploaded diagram → SVG hotspots wired to the same RAG panel — the universal fallback for topics primitives can't express. Same provenance and caching rules. Plus README with both headline claims linked to evidence, and a 2-minute demo script.

---

## 8. Repo layout

```
aakar/
  apps/web/                 # Next.js: viewer, panel, admin review, library
  services/api/             # FastAPI: ingest, retrieve, generate, critic, cache
  packages/scenespec/       # scenespec.schema.json + codegen outputs
  specs/golden/             # hand-written Phase 1 specs
  evidence/                 # gate screenshots & transcripts (committed)
  lightningparse-issues/    # minimal repros for parser bugs found en route
  data/                     # uploads (gitignored), qdrant volume
  tests/
  DECISIONS.md  PROGRESS.md  README.md  config.yaml
```

---

## 9. Testing strategy

- Compiler totality via hypothesis over schema-valid specs; rejection tests for each constraint violation
- Codegen drift test (D7) in CI
- Retrieval tests: alias matching, widening trigger, score floors
- Cache tests: hit above threshold, miss below, scope isolation between parts/topics
- Critic-loop tests in replay: a seeded bad spec must trigger exactly the expected repair path
- Citation integrity: every panel sentence maps to a retrieved chunk with a page number (structural test on the response contract)

---

## 10. Reporting format (every gate)

1. What was built (short)
2. Evidence — pasted terminal output and files in `evidence/`, never paraphrase
3. Metrics as applicable (completeness %, cache hit rate, cost)
4. Cost incurred this phase (from `llm_calls`)
5. Open issues / deferred decisions
6. Next-phase plan — then **stop and wait for approval**

---

## 11. Amendment log

**v1.1 — 2026-08-23.** Architect rulings on the pre-Phase-0 review recorded in `DECISIONS.md`
and `GAPS.md`. Only §3 was edited; §5's decision text is unchanged.

- §3 Bookkeeping — table list restated per D-002 (`spec_versions`, not `specs`) and extended
  with `users`, `documents`, `corpora` per D-011; `owner_id` required on user-scoped tables.
- §3 Auth — new pinned entry per D-011, resolving G-01. Aakar v1 is single-owner by design,
  not by omission; multi-user is vNext.
- §3 Testing — `fast-check` pinned alongside `hypothesis` per D-001. §7 Phase 1's
  "hypothesis-generated specs" should be read as "property-test-generated".

**Amended by decision, text unchanged.** These two decisions correct flaws in §5 and are
binding, but §5 is left as written so the log can be diffed against the original:

- **D2** (§5) is strengthened by **D-008** — the validator additionally checks each part's
  `provenance.evidence` against the text of its cited chunks. As written, D2's deterministic
  half verifies only that a cited chunk id exists.
- **D4** (§5) is corrected by **D-007** — the semantic answer cache is scoped to
  `(corpus_id, topic, part)`, not `(topic, part)`. One owner can upload two chapters on the
  same topic, so document identity must be in the key.

Folding these into §5 directly is an architect call and has not been made.
