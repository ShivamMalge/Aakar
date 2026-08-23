# DECISIONS.md

Decision log for Aakar, per working rule 4 (*ambiguity protocol: pick the simplest option
consistent with the spec, log it here, continue*) and rule 9.

**Governing sources:** `aakar-claude-code-prompt.md` (the spec — v1.0) and `phases.md`
(execution roadmap). On conflict the spec wins; conflicts are recorded here rather than
resolved silently. Neither document is currently committed to this repository — they should
be, so that entries below can be diffed against the text they interpret.

Entries are `Accepted (pending architect review)` unless stated otherwise: they unblock work
under rule 4 but none of them override the architect. Open items with no defensible default
live in `GAPS.md`.

Status: all entries below were logged **before Phase 0 started**, from a read of the two
source documents. No code exists yet.

---

## D-001 — Property-test generator for the SceneSpec compiler: fast-check, not hypothesis

**Status:** Accepted (pending architect review) · **Phase:** 1 · **Spec conflict:** yes

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

**Status:** Accepted (pending architect review) · **Phase:** 1–2 · **Spec conflict:** yes

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

**Status:** Accepted (pending architect review) · **Phase:** 1 (route shape), 3 (use)

D3 screenshots a spec that has not yet passed the human gate, while rule 8 says nothing enters
the library until the architect approves it. The spec never says how the viewer route reaches an
unapproved spec.

**Decision:** the route takes an explicit draft selector —
`/render/{topic_id}?spec_version={id}&angle=n` — which resolves a specific row in
`spec_versions` regardless of status. Without that parameter the route serves only the
`approved` version, and 404s if none exists. Draft mode is gated by the same admin
authorization as the Phase 3 review UI (see `GAPS.md` G-01: that authorization does not yet have
a design).

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

**Status:** Accepted (pending architect review) · **Phase:** 1

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

**Status:** Accepted (pending architect review) · **Phase:** 2 · **Spec correction**

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

**Status:** Accepted (pending architect review) · **Phase:** 3 · **Spec strengthening**

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

**Status:** Accepted (pending architect review) · **Phase:** 0 (wiring), 1 (harness), 3 (use)

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

**Status:** Accepted (pending architect review) · **Phase:** 0–1

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
