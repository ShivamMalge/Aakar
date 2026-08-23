# GAPS.md

Open gaps in `aakar-claude-code-prompt.md` (v1.0) and `phases.md` — things the two documents
assume, claim, or gate on, but do not specify or measure. Items that had a defensible default
were resolved under rule 4 and moved to `DECISIONS.md`; what remains here either needs the
architect, or needs a measurement nobody has scheduled.

Each entry names the phase where it must be closed. Ordered by severity, not by phase.

Status: written before Phase 0 started, from a read of the two source documents. No code exists
yet, so nothing here is a finding about the implementation.

---

## G-01 — There is no identity or authorization model · **critical** · close in Phase 0

Privacy is load-bearing from Phase 2 onward and undesigned:

- Rule 10 makes uploads "private, per-user"; §7 Phase 4 says "private per-user storage".
- §3's SQLite tables (`topics`, specs, `approvals`, `llm_calls`, cached answers) contain **no
  users table**, and no upload/document table either.
- No auth library is pinned in §3.
- §7 Phase 3's "admin route" and rule 8's approval gate imply an admin role with no stated
  mechanism.
- §7 Phase 4's "shareable read-only viewer route" implies deliberately *unauthenticated* access
  to some topics — so the system has at least three principals (owner, admin, anonymous
  share-link visitor) and defines none of them.

D-004 and D-007 both defer to a decision that does not exist: D-004 gates draft renders on
"the same admin authorization as the review UI", D-007 keys the cache on a `corpus_id` whose
ownership model is undefined.

**Needed:** a decision on principals, on how uploads bind to an owner, on what a share link
grants, and on how the admin route is protected. This is cheap now — the SQLite schema is
written in Phase 0 — and expensive after Phase 2 has data in it.

**Blocked on:** architect. This is the one item where proceeding on a guess is worse than
asking.

---

## G-02 — Citation correctness is never measured · **high** · close in Phase 2

D6 states the law: "No citation → the sentence doesn't ship." §9's only enforcement is
"citation integrity: every panel sentence maps to a retrieved chunk with a page number
(structural test on the response contract)". A structural test proves a page number is
*present*, not that the page *supports* the sentence. Nothing in Phase 2 or Phase 3 measures
whether citations are correct.

This is the evidence behind headline claim #2. As specified, the Phase 2 gate would pass with
uniformly wrong page numbers.

**Proposed:** hand-verify ~20 citations from the Phase 2 transcripts against the OpenStax PDF
and report the accuracy rate in the gate report. An afternoon of work; it is the number that
makes the claim credible.

---

## G-03 — The cache hit-rate gate has no false-hit counterpart · **high** · close in Phase 2

Both documents gate Phase 2 on ">60% hit rate on the paraphrase set" at cosine ≥ 0.92. The
metric is one-sided and is trivially satisfied by lowering the threshold — which is precisely
how the system starts serving confidently wrong cached answers. D4's "similar question" note
mitigates the UX but not the correctness.

**Proposed:** pair the hit-rate table with a **false-hit count** over a set of near-miss
questions that are lexically close but semantically distinct and *should* miss. Report both
numbers, and calibrate the 0.92 default against them rather than accepting it as given.

---

## G-04 — The critic loop's efficacy is never measured · **medium** · close in Phase 3

D3 spends up to two repair rounds and real VLM cost per topic. §9 tests the *mechanism* ("a
seeded bad spec must trigger exactly the expected repair path"), and Phase 3's results table
records repair rounds — but nothing establishes that the critic improves the output. A vision
model judging screenshots of untextured primitives may be close to noise.

**Proposed:** run the 5-topic pilot batch twice, once with the critic disabled, and compare
completeness % and final status. Cheap in replay mode. A null result is itself worth knowing and
worth reporting honestly.

---

## G-05 — The Phase 4 gate does not test the privacy it claims · **high** · close in Phase 4

Phase 4 ships "private per-user storage" and a public share link; its gate is a numbered
screenshot walkthrough plus a Lighthouse pass. Rule 10 — the project's one legal-risk rule —
has no test anywhere in either document.

**Proposed:** add a hard gate item. An unauthenticated request, and a request from a *different*
authenticated user, must both fail to fetch another user's PDF, chunks, draft specs, and cached
answers. Paste the 403s as evidence. Depends on G-01.

---

## G-06 — Retrieval is never re-validated on generated topics · **medium** · close in Phase 3

Phase 2 proves part-scoped retrieval against the golden specs' hand-written part names and
aliases, which were tuned by hand. Phase 3 generates part names and aliases from a model. D5's
scoping, alias matching, and thin-results widening are never re-checked against generated
vocabulary, which is where alias quality is likely to be worst.

**Proposed:** re-run the Phase 2 retrieval and widening tests against at least one *generated*
topic as part of the Phase 3 gate.

---

## G-07 — No story for re-generating or revising an approved topic · **medium** · close in Phase 4

`spec_versions` tracks status transitions, but neither document says what happens when an
already-approved topic is regenerated: whether approval is revoked, whether a share link pins a
`spec_version` or follows the current approved one, or what a reader sees mid-revision. D4's
"generate once per topic; serve forever" assumes revision never happens.

Related: the per-(topic, part) summary cards and the semantic answer cache are keyed on part
identity. If a revised spec renames or removes a part, its cached answers are silently orphaned
or misattached.

**Proposed:** decide whether share links pin a version, and define cache invalidation on spec
revision. Cheap to decide now, painful once the library has readers.

---

## G-08 — Headline claim #2 needs a scope qualifier · **medium** · close in Phase 5 (README)

"A semantic cache makes marginal cost per user approach zero" holds when users share a source
document — the openly licensed public library. Under D-007's corrected cache scoping (and under
rules 6 and 10, which force it), private uploads amortize *within* one user, not across users.

The claim is still true and still worth making. It needs the qualifier, or it will be
challenged in exactly the conversation where it matters most. §7 Phase 5 already asks for an
"honest scope statement" — this belongs in it.

---

## G-09 — The pilot is N=5 · **low** · acknowledge in Phase 5 (README)

Phase 3's evidence is 5 topics with human approve/reject as the outcome measure. That is an
anecdote, not a result — fine for the project's purpose, but §7 Phase 5 wants both headline
claims "linked to evidence". State the sample size next to the completeness numbers rather than
letting the table imply more than it shows.

---

## G-10 — Exploded view versus the parent/child hierarchy · **low** · close in Phase 1

§4 computes the exploded view "radially from the assembly centroid, no schema field needed",
while parts form a tree via `parent_id`. Exploding every part radially from a single global
centroid will separate children from their parents. This is harmless for concentric topics
(Earth layers) and may look wrong for nested ones (a lens parented to an eyeball).

**Proposed:** decide during 1.4 whether explosion operates on top-level parts only, carrying
children with them, or on all parts independently. Visual call, best made in the running viewer.

---

## G-11 — Effort estimates are optimistic · **informational**

`phases.md` marks Phase 1 at 2–3 sessions for nine geometry builders, cutaway, exploded view,
property tests, and three hand-tuned golden specs — of which 1.5 ("Shivam tunes visually") is
open-ended human work. Phase 2 at 2–3 sessions covers ingestion, Qdrant, hybrid RRF retrieval,
summary cards, chat, panel UI, and a benchmark harness. The document already hedges ("rough
Claude Code sessions, not promises"), so this is a note rather than a finding — but the gates,
not the estimates, should decide when a phase ends.
