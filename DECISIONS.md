# DECISIONS.md

Decision log for Aakar, per working rule 4 (*ambiguity protocol: pick the simplest option
consistent with the spec, log it here, continue*) and rule 9.

**Governing sources:** `aakar-claude-code-prompt.md` (the spec — v1.1) and `phases.md`
(execution roadmap), both committed at the repo root as of task 0.0 so the entries below can be
diffed against the text they interpret. On conflict the spec wins; conflicts are recorded here
rather than resolved silently.

D-001 … D-010 were logged **before Phase 0 started**, from a read of the two source documents,
and **all were accepted by the architect on 2026-08-23**. D-011 … D-013 record rulings made in
that same review. Open items live in `GAPS.md`.

---

## D-001 — Property-test generator for the SceneSpec compiler: fast-check, not hypothesis

**Status:** Accepted · **Phase:** 1 · **Spec conflict:** yes

Spec §3 pins `pytest` + `hypothesis`, and §7 Phase 1 requires "compiler is total over
schema-valid specs (hypothesis-generated specs never crash it)". But §3 also pins the compiler
to TypeScript, tested under vitest. Hypothesis cannot fuzz it in-process. `phases.md` 1.7
already substitutes fast-check without noting that §3 says "pinned — do not substitute".

**Decision:** use **fast-check** inside the vitest suite for compiler totality and rejection
tests. `hypothesis` remains pinned and is used for property tests on the Python side
(validator, chunker, cache scoping).

**Rationale:** in-process generation gives shrinking on failure, which is the entire value of
property testing. The alternative — hypothesis writing a corpus of spec JSON to disk for a
vitest runner to consume — keeps one generator feeding both stacks but loses shrinking and adds
a build step across the language boundary. If the architect wants a single generator, that is
the fallback, and it is a Phase 1 change, not a Phase 0 one.

**Consequence:** §3's pinned-stack list should gain `fast-check`; §7 Phase 1's wording should
say "property-test-generated" rather than "hypothesis-generated".

---

## D-002 — The spec table is named `spec_versions`

**Status:** Accepted · **Phase:** 0 · **Spec conflict:** naming drift only

Spec §3 lists the SQLite tables as `topics, specs, approvals, llm_calls, cached answers`;
`phases.md` 0.5 lists `topics, spec_versions, approvals, llm_calls, qa_cache_meta`.

**Decision:** follow `phases.md`. Tables are `topics`, `spec_versions`, `approvals`,
`llm_calls`, `qa_cache_meta`.

**Rationale:** D3 requires that *every* generation attempt's spec, screenshots and critique are
stored. That is a versioned table by definition, and `specs` invites a single-row-per-topic
design that D3 forbids. `qa_cache_meta` likewise signals that the vectors live in Qdrant and
SQLite holds only bookkeeping.

---

## D-003 — Golden specs use a `["golden"]` provenance sentinel, and are backfilled in Phase 2

**Status:** Accepted · **Phase:** 1–2 · **Spec conflict:** yes

Spec §4 makes `≥1 provenance.chunk_ids` entry a hard schema constraint, and D2 has the
validator check that the cited chunk ids exist. Phase 1 hand-writes golden specs with no corpus
ingested — there are no chunk ids to cite. `phases.md` 1.5 introduces `chunk_ids: ["golden"]`
"for now"; the spec does not acknowledge it, and no task in any phase removes it.

**Decision:**
1. `"golden"` is a reserved chunk id. The schema still requires a non-empty `chunk_ids` array;
   the validator's existence check treats `"golden"` as satisfied.
2. A **Phase 2 task backfills real chunk ids** into `specs/golden/*.json` once the OpenStax
   corpus is ingested, and a test asserts that no spec outside `specs/golden/` uses the
   sentinel.
3. After backfill, the sentinel remains legal only for specs under `specs/golden/`.

**Rationale:** the sentinel is unavoidable — Phase 1 exists precisely to prove the schema before
any corpus exists. The risk is not the sentinel, it is the sentinel becoming permanent and
quietly hollowing out rule 6. Scheduling the backfill and testing the boundary contains that.

---

## D-004 — `/render/{topic_id}` serves unapproved specs only in an explicit draft mode

**Status:** Accepted · **Phase:** 1 (route shape), 3 (use)

D3 screenshots a spec that has not yet passed the human gate, while rule 8 says nothing enters
the library until the architect approves it. The spec never says how the viewer route reaches an
unapproved spec.

**Decision:** the route takes an explicit draft selector —
`/render/{topic_id}?spec_version={id}&angle=n` — which resolves a specific row in
`spec_versions` regardless of status. Without that parameter the route serves only the
`approved` version, and 404s if none exists. Draft mode is gated on the **owner session** (D-011)
— the same check that protects the Phase 3 review UI.

**Rationale:** keeps the approval gate a property of the *default* path, so a missing check
fails closed. The library, share links and the Phase 4 flow all use the default path and cannot
address a draft even by guessing.

---

## D-005 — Everything committed under `evidence/` comes from the open corpus

**Status:** Accepted · **Phase:** 2–5

Spec §8 commits `evidence/` to the repository; rule 10 makes user uploads private and per-user;
Phase 4's gate is an end-to-end capture that begins with "upload chapter".

**Decision:** all transcripts, screenshots and Q&A captures committed to `evidence/` are
produced against the openly licensed test corpus (OpenStax). The Phase 4 demo upload is an
OpenStax chapter uploaded through the real upload flow, not a third-party textbook. `data/`
stays gitignored per §8.

**Rationale:** without this the repository itself violates rule 10 at the Phase 4 gate, and the
violation is committed to git history where it is expensive to remove.

---

## D-006 — `importance` is reserved in v1 with no behavior

**Status:** Accepted · **Phase:** 1

`importance: "core" | "secondary"` is defined in §4 and consumed by nothing: no viewer behavior
in §4, no validator rule, no weighting in D2's completeness check.

**Decision:** the field stays in the schema, is validated as an enum, and drives **no** behavior
in v1. It is not used to weight completeness, filter labels, or order the exploded view.

**Rationale:** removing it is a breaking schema change for a field the architect may have
intended for label-density or level-of-detail work; wiring it into completeness scoring would
silently change what D2 measures. Reserving it is the smallest move. If it is meant to weight
completeness, that is a deliberate change to D2 and should be logged as its own decision.

---

## D-007 — The semantic answer cache is keyed by corpus, not only by (topic, part)

**Status:** Accepted · **Phase:** 2 · **Spec correction**

D4 scopes the cache to `(topic, part)`. Rule 10 makes uploads private and per-user, and rule 6
requires answers to cite pages in *the user's own* material. Two users who upload different
chapters on the same topic therefore collide: user B can be served an answer generated from user
A's document — wrong page numbers at best, A's chapter text disclosed to B at worst.

**Decision:** the cache scope is `(corpus_id, topic, part)`, where `corpus_id` identifies the
ingested document set the answer was generated from. Shared/public library topics have a shared
`corpus_id` and so still amortize across all their readers; private uploads each get their own.
A Phase 2 test asserts that a question answered against corpus A never returns a cached hit for
an identical question against corpus B.

**Rationale:** this is the smallest change that keeps D4 consistent with rules 6 and 10. See
`GAPS.md` G-08 — it narrows, but does not invalidate, the "marginal cost approaches zero"
headline claim, and the README wording needs to reflect that.

---

## D-008 — Groundedness gets a deterministic evidence check, not only a critic judgment

**Status:** Accepted · **Phase:** 3 · **Spec strengthening**

D2 splits groundedness into "verify chunk_ids exist" (deterministic) and "the critic judges
plausibility". As written, the deterministic half only checks that an id string is present in
the database — a model satisfies it by citing any real chunk. The critic per D3 receives the
checklist, the spec and screenshots; it sees `provenance.evidence` inside the spec but never the
text of the cited chunks, so nothing in the pipeline ever compares the two.

**Decision:** the validator additionally checks each part's `provenance.evidence` against the
text of its cited chunks — normalized substring match first, falling back to an embedding
similarity threshold (config, default to be calibrated in Phase 3) for lightly reworded
evidence. Failure flags the part as ungrounded and feeds the repair prompt.

**Rationale:** `evidence` is described in §4 as a quotation from the chunk, so the strict check
is nearly free and turns the load-bearing half of D2 into something testable. It also keeps
groundedness from depending on a vision model reading a screenshot, which is the wrong modality
for a text-provenance question.

---

## D-009 — Playwright runs from `services/api` against the web app

**Status:** Accepted · **Phase:** 0 (wiring), 1 (harness), 3 (use)

§3 specifies "Playwright against the web viewer's `/render/{topic_id}?angle=n` route" without
saying which stack drives it. `phases.md` builds the harness in Phase 1 (web) and consumes it
from the Phase 3 pipeline (Python). This is the only cross-stack runtime dependency in the
project and it is invisible until Phase 3.

**Decision:** the generation pipeline drives **playwright-python** from `services/api` against a
running web server. `make dev` and the Phase 3 batch runner both ensure the web app is up; the
Makefile and CI account for the browser dependency from Phase 0 onward. The Phase 1 screenshot
harness is written as a thin CLI over the same code path so the gate captures and the critic
captures cannot drift apart.

**Rationale:** the consumer is Python, and a Python-driven harness avoids serializing a
screenshot request across a second interface. Deciding it in Phase 0 costs a Makefile target;
discovering it in Phase 3 costs a re-plumb during the most expensive phase.

---

## D-010 — The schema may still change through the Phase 1 gate, and freezes there

**Status:** Accepted · **Phase:** 0–1

Phase 0 authors the schema; Phase 1's stated purpose is to find out whether it is expressive
enough ("writing these by hand is the point"). Nothing says what happens when Phase 1 proves it
is not.

**Decision:** schema revisions are **in scope for Phase 1** and expected. Each revision bumps
`schema_version`, re-runs `make codegen`, and must leave the drift test green. Phase 1 does not
close until the schema has stopped moving; the Phase 1 gate report states the final
`schema_version`. After that gate, schema changes are vNext.

**Rationale:** the alternative is discovering a missing geometry type in Phase 1 and treating it
as a Phase 0 regression, which encourages working around the schema rather than fixing it —
exactly the failure the golden specs exist to prevent.


---

## D-011 — Aakar v1 is single-owner: two principals, `owner_id` everywhere, multi-user is vNext

**Status:** Accepted (architect ruling, 2026-08-23) · **Phase:** 0 · **Resolves:** G-01

The spec assumed per-user privacy without defining a principal, a users table, or an auth
mechanism (G-01). The architect's ruling: **do not build multi-tenancy.**

**Decision — exactly two principals:**

1. **Owner** — a single authenticated user. All uploads, documents, corpora, drafts and
   approvals belong to the owner. The admin/review route is simply "is the owner logged in".
2. **Anonymous share-link reader** — unauthenticated; may view one topic's approved spec and its
   cached summaries. Nothing else. See D-012 for what this principal may spend.

**Schema:** Phase 0 adds `users`, `documents` and `corpora` tables, and **every user-scoped
table carries an `owner_id` column from day one** even though only one owner exists — so vNext
multi-user becomes a policy change rather than a migration.

**Auth library (pinned in §3):** the **API owns the session** — `pyjwt` (HS256 over
`AAKAR_AUTH_SECRET`) for the session token, `passlib[argon2]` for the owner credential hash, and
a `require_owner` FastAPI dependency. No auth library on the web side.

**Rationale:** every protected resource — PDFs, chunks, draft specs, cached answers — lives
behind FastAPI, so the check belongs where the data is. Auth.js was the obvious alternative and
was rejected: its default v5 session token is a JWE rather than a plain JWS, which makes
verification from Python awkward, and it would put the authority for the session in the stack
that holds none of the protected data. A single HS256 cookie minted and verified in one place is
smaller and harder to get wrong. vNext can swap the credential check for an OAuth provider
without changing how the API verifies.

**Explicitly vNext:** real multi-user auth, per-user isolation testing beyond the single-owner
case, and any sharing model richer than one anonymous read-only link.

**Consequence:** unblocks D-004 (draft renders gate on the owner session) and G-05 (the Phase 4
privacy gate now has something to assert). **D-007 stands unchanged** — one owner can upload two
chapters on the same topic, so `corpus_id` scoping is still required; single-owner does not make
the cache key safe.

---

## D-012 — Share links disable free-form chat

**Status:** Accepted (architect ruling, 2026-08-23) · **Phase:** 4 · **Resolves:** G-12

Phase 4's share link is "read-only", but the RAG panel includes free-form chat and a cache miss
calls the LLM. An anonymous visitor could therefore spend real money from a public URL, in a
loop, with no account.

**Decision:** anonymous share-link readers get the **cached summary card and suggested questions
only; free-form chat is disabled**. Suggested questions are pre-generated and cached per
(corpus, topic, part), so tapping one is a cache read, not a generation.

If chat is ever enabled for share links, it requires **both** a per-link rate limit **and** a
hard per-link daily spend cap, enforced server-side — not one or the other. That is a vNext
decision, not a v1 toggle.

**Rationale:** the preferred default from the ruling, and the only option where the spend
ceiling is structural rather than configured. A rate limit plus cap still leaks money at the cap
and needs monitoring nobody has scheduled.

**Gate (Phase 4):** a scripted anonymous loop against a share link must produce an `llm_calls`
delta of zero.

---

## D-013 — Share links pin a `spec_version`; revision invalidates renamed and removed parts

**Status:** Accepted (architect ruling, 2026-08-23) · **Phase:** 4 · **Resolves:** G-07

Neither document said what happens when an already-approved topic is regenerated. D4's "generate
once per topic; serve forever" assumes revision never happens.

**Decision:**
1. A share link **pins the `spec_version` it was created from**. A revision does not silently
   change what an existing reader sees.
2. Revising an approved spec **invalidates cached answers and summary cards for parts that were
   renamed or removed**; parts surviving unchanged keep their cache.

**Rationale:** the cache and summary cards are keyed on part identity (D-007), so a rename
silently orphans or misattaches cached answers — the failure is invisible and serves stale text
under a new label. Pinning the version keeps a shared URL stable, which is the only thing a
share link promises.

---

## D-014 — Zod v4 on the web side

**Status:** Accepted · **Phase:** 0 · **Taken during implementation**

`json-schema-to-zod` 2.8.1 emits zod v4 idioms (`z.core.$ZodIssue` in the `oneOf`
`superRefine` block). With the originally pinned zod v3.23, `tsc --noEmit` failed on the
generated file — the schema validated at runtime but the project would not typecheck.

**Decision:** the web stack uses `zod@^4`.

**Rationale:** the generator and the runtime have to agree, and the generated file is the
one thing that must not be hand-patched (D7). Downgrading the generator instead would pin
us to an older codegen for a schema we expect to revise through Phase 1 (D-010). Nothing
else in the project consumed zod yet, so the cost was zero.

---

## D-015 — The schema is dereferenced before zod codegen

**Status:** Accepted · **Phase:** 0 · **Taken during implementation**

`json-schema-to-zod` does not follow `$ref` into `$defs`. Fed the schema directly it
emitted `z.any()` for `parts`, `cutaway` and `camera_hint` — a zod schema that typechecks,
runs, and validates **nothing**. That would have satisfied the Phase 0 gate while quietly
removing every part-level constraint from the web stack.

**Decision:** `packages/scenespec/codegen.mjs` fully inlines `$defs` before generating.
The schema has no cycles — `parent_id` is a string, not a `$ref` to `Part` — so inlining
terminates; the deref function raises on both an unresolved `$ref` and a cyclic one rather
than falling back to `any`.

**Rationale:** D7 says the schema is the enforced single source of truth *on both stacks*.
A generator that silently degrades to `any` breaks that while looking healthy, which is
the worst failure mode available. The mirror test suite
(`apps/web/src/scenespec/generated.test.ts`) exists to catch a regression here: it asserts
the zod side rejects exactly what the pydantic side rejects.

---

## D-016 — `AAKAR_AUTH_SECRET` must be at least 32 bytes

**Status:** Accepted · **Phase:** 0 · **Taken during implementation**

PyJWT emitted `InsecureKeyLengthWarning` during the auth tests: the dev default was 21
bytes, under the 32-byte floor RFC 7518 §3.2 sets for HS256.

**Decision:** `Settings.from_env()` refuses to construct with a shorter secret. The
`.env.example` default is long enough to be valid and named so it cannot be mistaken for
production-ready.

**Rationale:** a weak session key is exactly the kind of thing that ships because it only
ever produced a warning. Failing at boot costs one line and makes the floor
non-negotiable.
