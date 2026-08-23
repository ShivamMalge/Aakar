# GAPS.md

Open gaps in `aakar-claude-code-prompt.md` (v1.1) and `phases.md` — things the two documents
assume, claim, or gate on, but do not specify or measure.

**All items below were ruled on by the architect on 2026-08-23.** Nothing here is still awaiting
a decision. Each entry now carries a disposition: **Resolved** (a decision exists in
`DECISIONS.md`), **Scheduled** (accepted as a task and gate item in `phases.md`, closing in the
named phase), or **Open** (a call deliberately deferred to the phase where it can be made well).

Status: written before Phase 0 started, from a read of the two source documents. Nothing here is
a finding about the implementation.

---

## G-01 — There is no identity or authorization model · **critical**
### → **Resolved** by D-011 · closed in Phase 0

Privacy was load-bearing from Phase 2 onward and undesigned: rule 10 promised per-user uploads,
§3's tables had no `users` row, no auth library was pinned, and the admin route, the owner's
private data and the anonymous share link implied three principals that nothing defined.

**Ruling:** do not build multi-tenancy. Aakar v1 has exactly two principals — **owner** (a single
authenticated user; the review route is "is the owner logged in") and **anonymous share-link
reader** (one topic's approved spec and cached summaries, nothing else). Phase 0 adds `users`,
`documents` and `corpora`, and every user-scoped table carries `owner_id` from day one so vNext
multi-user is a policy change, not a migration. Auth is pinned in §3: `pyjwt` + `passlib[argon2]`,
API-side session, no web auth library. Real multi-user auth is explicitly vNext.

Unblocks D-004 (draft renders gate on the owner session) and G-05. **Does not** affect D-007:
one owner can upload two chapters on the same topic, so corpus scoping is still required.

---

## G-12 — An anonymous share link can spend money · **high**
### → **Resolved** by D-012 · test closes in Phase 4

*Raised by the architect during the 2026-08-23 review.*

Phase 4's share link is "read-only", but the RAG panel includes free-form chat and a cache miss
calls the LLM. An anonymous visitor can therefore spend real money from a public URL, and can do
it in a loop. "Read-only" describes what a visitor can *write*, not what they can *cost*.

**Ruling:** share links expose cached summaries and suggested questions only, with **chat
disabled** — the preferred default, and the only option where the spend ceiling is structural.
Enabling chat on share links later would require both a per-link rate limit and a hard per-link
daily spend cap.

**Gate (Phase 4):** a scripted anonymous loop against a share link produces an `llm_calls` delta
of zero.

---

## G-02 — Citation correctness is never measured · **high**
### → **Scheduled** · task 2.10, Phase 2 gate

D6 states the law — "no citation → the sentence doesn't ship" — and §9's only enforcement is a
structural test that a page number is *present*. Nothing checks the cited page *supports* the
sentence. As specified, the Phase 2 gate would pass with uniformly wrong page numbers, and this
is the evidence behind headline claim #2.

**Accepted:** hand-verify ~20 citations from the Phase 2 transcripts against the source PDF;
report the accuracy rate in the gate report.

---

## G-03 — The cache hit-rate gate has no false-hit counterpart · **high**
### → **Scheduled** · task 2.7, Phase 2 gate

Both documents gate Phase 2 on ">60% hit rate at cosine ≥ 0.92". The metric is one-sided and is
trivially satisfied by lowering the threshold — which is exactly how the system starts serving
confidently wrong cached answers.

**Accepted:** pair the hit-rate table with a **false-hit count** over a near-miss set of
lexically close but semantically distinct questions that should miss, and calibrate the 0.92
default against both numbers rather than accepting it as given.

---

## G-04 — The critic loop's efficacy is never measured · **medium**
### → **Scheduled** · task 3.6, Phase 3 gate

D3 spends up to two repair rounds and real VLM cost per topic. §9 tests the *mechanism*; nothing
establishes that the critic improves the output. A vision model judging screenshots of untextured
primitives may be close to noise.

**Accepted:** run the pilot batch twice, once with the critic disabled, and compare completeness
% and final status. Cheap in replay. **A null result is a real finding and gets reported as
one** — not buried.

---

## G-05 — The Phase 4 gate does not test the privacy it claims · **high**
### → **Scheduled** · tasks 4.2 / 4.5, Phase 4 gate

Phase 4 ships private storage and a public share link; its gate was screenshots plus a
Lighthouse pass. Rule 10 — the project's one legal-risk rule — had no test anywhere.

**Accepted as a hard gate item:** an unauthenticated request must fail to fetch owner-private
PDFs, chunks, draft specs and cached answers. Paste the 403s. Now assertable because D-011
defines the principals.

---

## G-06 — Retrieval is never re-validated on generated topics · **medium**
### → **Scheduled** · task 3.8, Phase 3 gate

Phase 2 proves part-scoped retrieval against golden specs' hand-tuned part names and aliases.
Phase 3 generates them from a model, and D5's scoping, alias matching and widening are never
re-checked against generated vocabulary — where alias quality is likely to be worst.

**Accepted:** re-run the Phase 2 retrieval and widening tests against at least one generated
topic as part of the Phase 3 gate.

---

## G-07 — No story for re-generating or revising an approved topic · **medium**
### → **Resolved** by D-013 · closes in Phase 4

`spec_versions` tracked status transitions, but nothing said whether approval is revoked on
regeneration, whether a share link pins a version, or what happens to cached answers keyed on a
part that was renamed or removed.

**Ruling:** share links **pin a `spec_version`**, and spec revision **invalidates cached answers
for renamed or removed parts**; surviving parts keep their cache. Logged as D-013, gated in
Phase 4.

---

## G-08 — Headline claim #2 needs a scope qualifier · **medium**
### → **Scheduled** · task 5.2 (README), Phase 5 gate

"A semantic cache makes marginal cost per user approach zero" holds when readers share a source
document. Under D-007's corpus-scoped cache — which rules 6 and 10 force — separate uploads
amortize within one owner, not across users. The claim is true and worth making; it needs the
qualifier, or it gets challenged in exactly the conversation where it matters most.

**Accepted:** state it in the README's honest-scope section.

---

## G-09 — The pilot is N=5 · **low**
### → **Scheduled** · task 5.2 (README), Phase 5 gate

Phase 3's evidence is 5 topics with human approve/reject as the outcome. That is an anecdote, not
a result — fine for the project's purpose, but §7 Phase 5 wants both claims "linked to evidence".

**Accepted:** state the sample size next to the completeness numbers rather than letting the
table imply more than it shows.

---

## G-10 — Exploded view versus the parent/child hierarchy · **low**
### → **Open by design** · decide in task 1.4, log in `DECISIONS.md`

§4 computes the exploded view "radially from the assembly centroid", while parts form a tree via
`parent_id`. Exploding every part from a single global centroid separates children from parents:
harmless for concentric topics (Earth layers), likely wrong for nested ones (a lens parented to
an eyeball).

**Ruling:** the implementer's call, made in the running viewer during 1.4 — top-level parts only,
carrying children with them, or every part independently. Whichever is picked gets logged. This
is a visual judgment that cannot be made well on paper.

---

## G-11 — Effort estimates are optimistic · **informational**
### → **Noted and agreed**

Phase 1 is marked 2–3 sessions for nine geometry builders, cutaway, exploded view, property tests
and three hand-tuned golden specs — of which 1.5 is open-ended human work. Phase 2 is marked the
same for ingestion, Qdrant, hybrid RRF, summary cards, chat, panel UI and a benchmark harness.

**Ruling:** **gates end phases, not estimates.** Recorded in the `phases.md` preamble.
