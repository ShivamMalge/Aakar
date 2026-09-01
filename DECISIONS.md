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
2. A **Phase 2B task (2B.11) backfills real chunk ids** into `specs/golden/*.json` once the OpenStax
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

---

## D-017 — The exploded view moves top-level parts only, carrying their children

**Status:** Accepted · **Phase:** 1 · **Resolves:** G-10

G-10 left this open by design: §4 computes the exploded view "radially from the assembly
centroid" while parts form a tree via `parent_id`, and exploding every part from one global
centroid separates children from parents. The ruling was to make the call in the running
viewer during 1.4. Both readings were implemented and rendered.

**Decision:** explosion moves **top-level parts only; children ride along inside their parent.**
`per-part` remains in the code as a named mode because the comparison is worth keeping, but
`top-level` is the default and the only mode the viewer ships pointed at.

**What the render showed** (`evidence/phase1/animal_cell-angle0-explode0.6-{top-level,per-part}.png`):
in `per-part`, the nucleolus is pulled to the edge of the nucleus and half out of it. That is
not a clearer diagram, it is a false one — a nucleolus is *inside* a nucleus, and the same
happens to the fovea on the retina. In practice `parent_id` encodes containment, so moving a
child independently of its container always says something untrue.

**Consequence for Phase 3:** the generator should parent parts that move together, and a spec
that parents parts which do not will explode wrongly.

> **Superseded in part by D-031 (2026-08-26).** This entry originally read "in practice
> `parent_id` encodes containment" and told Phase 3 to treat it as "is contained by". That
> was too narrow, and the neuron stress fixture disproved it: 20 of its 39 parented pairs are
> `adjacent` and 11 are `surface_attached`, because a branching structure parents by
> connectivity — which is precisely what makes its exploded view carry subtrees correctly.
> **`parent_id` is a scene-graph relation, not a semantic claim.** The explosion ruling above
> is unaffected; only the justification changes. See D-031.

---

## D-018 — The schema declares an OpenAPI-style `discriminator` on `Geometry`; `schema_version` stays 1.0

**Status:** Accepted · **Phase:** 1 · **Taken during implementation**

D-015 stopped the zod side degrading to `z.any()` by dereferencing `$defs`, but the `oneOf`
still compiled to `z.any().superRefine(...)`. Two consequences neither the Phase 0 gate nor
its tests could see:

1. `SceneSpec["parts"][number]["geometry"]` inferred as **`any`** — so the compiler switch had
   no exhaustiveness checking on the one field where a missed case is a missing geometry type.
2. `superRefine` discards each branch's parse result, so **zod applied no geometry defaults**
   while pydantic did. A lathe with no `segments` reached the web compiler as `undefined` and
   the API as `32`. That is exactly the cross-stack drift D7 exists to prevent, and the drift
   test could not see it because both files were faithfully generated.

**Decision:** `$defs.Geometry` carries `"discriminator": { "propertyName": "type" }`, and each
branch annotates its tag as `{ "type": "string", "const": "..." }`. `json-schema-to-zod` then
emits `z.discriminatedUnion("type", [...])` and datamodel-code-generator emits a pydantic
tagged union (`discriminator="type"`). Both stacks improved from one annotation; neither
generated file is hand-edited, so D7 is intact.

**`schema_version` stays `"1.0"`.** D-010 says each Phase 1 revision bumps it. This revision
changes **no validation semantics** — `discriminator` is not a 2020-12 keyword, and a `const`
string was already a string. No document changes validity in either direction. Bumping would
have forced an edit to every golden spec and the §4 example to record a difference that does
not exist. Logged here rather than done silently, because "the schema changed but the version
did not" is exactly the kind of thing that should never be a silent call.

---

## D-019 — Golden specs omit `provenance.evidence`

**Status:** Accepted · **Phase:** 1 · **Spec interaction:** D-003, D-008

`evidence` is defined in §4 as a quotation *from the cited chunk*, and D-008 has the validator
match it against that chunk's text. Phase 1 golden specs cite the reserved `["golden"]`
sentinel (D-003): there is no chunk, so there is nothing to quote.

**Decision:** golden specs set `chunk_ids: ["golden"]` and **omit `evidence` entirely** (the
schema makes it optional). Phase 2B task 2B.11 adds real chunk ids and real quoted evidence
together, in one pass.

**Rationale:** the alternative is writing plausible textbook sentences into a field whose whole
contract is "this is quoted from the source". Those strings would sit in the repository looking
like citations, would survive into screenshots and demos, and D-008's matcher would have
nothing to check them against. An absent field is honest; a fabricated quotation is not, and
rule 6 is the one rule the project cannot afford to be loose about.

---

## D-020 — Translucent parts do not write depth

**Status:** Accepted · **Phase:** 1 · **Taken during implementation**

The first render of `human_eye` was a uniform grey ball. Every layered topic in v1's target
list — eye, cell, Earth's layers — is concentric translucent shells, and with depth writing on,
whichever shell draws first occludes every shell inside it.

**Decision:** `buildMaterial` sets `depthWrite: opacity >= 1`. Opaque parts are unaffected;
translucent parts blend rather than occlude.

**Rationale:** this is the difference between the schema looking inexpressive and the schema
working. It is a known trade — translucent parts no longer self-sort, which can look wrong on a
single strongly concave translucent part — but v1's vocabulary is convex primitives, where the
trade is nearly free. Logged because it changes what the Phase 3 VLM critic sees: a critic
judging the grey-ball render would have reported missing parts that were present all along.

---

## D-021 — A cutaway plane's normal points *away* from the camera it is meant to open

**Status:** Accepted · **Phase:** 1 · **Consequence for Phase 3**

`THREE.Plane(normal, constant)` keeps the half-space where `normal · p + constant >= 0`. The
first golden specs used `normal: [0, 0, 1]` with a camera on +Z, which discarded the *far*
hemisphere — a correct clip that is invisible, and indistinguishable in a screenshot from
clipping being switched off entirely.

**Decision:** golden specs author the cutaway normal pointing away from `camera_hint`
(`[0, 0, -1]` for a +Z camera). The compiler does not second-guess the authored plane.

**Rationale:** having the viewer flip the normal toward the camera would make the rendered
result depend on camera state, so the same spec would clip differently as a reader orbits —
and D1 makes the compiler's output a function of the spec alone. The cost is that this is an
authoring rule a generator can get wrong. **Phase 3 must state it in the generation prompt**,
and the critic should be able to see the difference — a cutaway that opens nothing looks
identical to no cutaway at all.

---

## D-022 — `instance_of`, and schema_version 1.1

**Status:** Accepted (architect ruling) · **Phase:** 1 · **Resolves:** the duplicate-name finding

Two parts named "Mitochondrion" in `animal_cell` is legal and correct — unique *ids* is the
real invariant. But name + aliases is the retrieval scope key (D5), so both parts scoped
retrieval identically: same citations, same chat thread, and a scope header that could not
tell the reader which one they clicked.

**Decision:** `Part.instance_of` (optional, string 1–80). When present it names the concept
the part is an instance of, and **retrieval scopes on that rather than on the part's own
name**. Parts sharing an `instance_of` are **one retrieval target**. `animal_cell`'s two
mitochondria carry it; the neuron stress fixture has 13 such groups over 31 parts.

Grouping is by **exact string equality** on `instance_of` — deliberately dumb, because the
alternative is fuzzy concept-matching inside the retrieval key, which is precisely where a
silent mis-scope would be invisible.

**`schema_version` goes to 1.1.** Unlike D-018 this *is* a validation-semantics change: a
document carrying `instance_of` is invalid under 1.0 and valid under 1.1. Every golden spec,
the §4 example and the whole fixture corpus were re-stamped.

**Consequence for Phase 2:** the cache key from D-007 is `(corpus_id, topic, part)`. "Part"
must now resolve to `instance_of` when present, or two mitochondria get two cache entries for
what is one question. That is a Phase 2B task (2B.4), not done here.

**Consequence for Phase 3:** the generator has to emit `instance_of` whenever it emits
repeated structures. Without it, every repeated part is its own retrieval target and the
panel gets duplicate scopes with identical text.

---

## D-023 — Referential constraints live in `packages/scenespec` and fire at parse

**Status:** Accepted (architect ruling) · **Phase:** 1 · **Supersedes** the Phase 1 placement

The three constraints JSON Schema cannot express — unique part ids, `parent_id` resolving, an
acyclic parent graph — were implemented in TypeScript only, inside `compile()`.

**The serious half was not the language, it was the trigger point.** Firing on compile meant
storage, the API, and anything that parsed without rendering skipped referential validation
entirely. Phase 3's generator parses and stores server-side and does not render until the
critic runs, so a structurally broken spec would have reached the repair loop as a *render
failure* rather than as a diagnosable validation error — and the loop cannot repair what it
cannot diagnose.

**Decision:**
1. The contract lives in `packages/scenespec` — `referential.ts` plus the Python mirror at
   `services/api/aakar/scenespec/referential.py`.
2. Both fire at **parse**: `parseSceneSpec` (web) and `parse_scene_spec` (api).
3. One fixture set drives both: `packages/scenespec/fixtures/referential/`. The cross-stack
   contract is the `(code, path)` pair; message text is each stack's own.
4. `compile()` still calls it defensively, because it accepts a SceneSpec from anywhere and
   must stay total.

**Explicitly NOT enforced, per the same ruling:** unique part *names* (an animal cell has
several mitochondria — that is what D-022 is for) and a *single root* (all three golden specs
are multi-root at 5, 11 and 11, and D-017's exploded view is defined over top-level parts,
plural). Both are recorded as fixtures that must be **accepted**, so a future implementer
cannot add them by accident.

**Found while writing the fixtures:** a self-parent was reported twice, once as `self_parent`
and once as a length-one `parent_cycle`. Both stacks now exclude self edges from cycle
detection — one defect, one code, or the repair prompt sees the same problem under two names.

---

## D-024 — Containment is a warning, never an error

**Status:** Accepted (architect ruling A(d)) · **Phase:** 1

D-017 made `parent_id` mean "is contained by", but nothing checked that a spec's parenting
reflected containment, so a spec that parents parts for convenience explodes wrongly with no
diagnostic.

**Decision:** the compiler measures a bounding-box containment ratio between each part and its
parent and emits a structured warning below 0.9 — `{code, partId, parentId, ratio, message}`,
carried in the compile result, never printed. It **never blocks**.

**Why a warning.** Run against the golden specs it produces exactly two, and both are correct
geometry with legitimate parenting:

| topic | part → parent | ratio |
| --- | --- | --- |
| `animal_cell` | `nuclear_envelope` → `nucleus` | 0.770 |
| `human_eye` | `fovea` → `retina` | 0.857 |

A nuclear envelope *surrounds* its nucleus and a fovea sits *on* the retina's surface. Neither
is a mistake, and an error would have blocked both. This is a curation signal (Rule 8) and a
Phase 3 repair-prompt input, nothing more.

**Measured on the part's own AABB**, deliberately not `Box3.setFromObject`, which walks
descendants — a parent's box would swallow its children and every part would look perfectly
contained.

**Known crudeness:** an AABB over a sphere over-reports. The fovea is genuinely on the retina;
it warns because their boxes clip at a corner. Tightening this to real geometry is vNext, and
the threshold should be calibrated against Phase 3's generated specs rather than against three
hand-written ones.

---

## D-025 — Zero-provenance parts are legal; `schema_version` → 1.2

**Status:** Accepted (architect ruling) · **Phase:** 1 · **Spec correction**

Phase 1 reported that a part with no provenance was inexpressible, because `chunk_ids`
carried `minItems: 1`. The architect's ruling reverses that, and it is the most
consequential change in this round.

**The problem.** Requiring at least one citation is safe for hand-authored specs and unsafe
for generated ones. When the Phase 3 generator proposes a part the chapter does not mention,
the schema leaves it one legal move: cite the nearest plausible chunk. **The schema made
fabricated provenance mandatory** — against the one claim this project rests on. It also made
two designed states unreachable: the curation gate's "no provenance" count, and the learning
view's "not in your chapter" tier.

**Decision:**
1. `chunk_ids` **may be empty**. Zero provenance is legal and meaningful: this part exists in
   the model and nothing in the student's chapter asserts it. The `minItems` keyword is
   *removed* rather than set to `0`, so it stops being an enumerable constraint the
   conformance corpus would need an impossible fixture for.
2. A derived **`provenance_strength`** per part, in three states, computed at parse on both
   stacks and **never author-supplied** — it is not a schema property, so
   `additionalProperties: false` already rejects any attempt to set it.
3. Zero-provenance parts render normally. They are a curation signal, not an error.
4. `schema_version` → **1.2**. Unlike D-018 this is a genuine validation-semantics change: a
   document with empty `chunk_ids` is invalid under 1.1 and valid under 1.2.

**Deviation from the ruling, stated plainly.** The ruling defines *strong* as ">= 1 chunk
naming the part" and *weak* as "chunks retrieved but not naming it". Whether a chunk **names**
the part can only be settled against chunk text, and **no corpus exists at parse time**. So
parse derives the document's own *claim*:

| state | condition |
| --- | --- |
| `none` | `chunk_ids` is empty |
| `weak` | `chunk_ids` non-empty, no `evidence` quotation |
| `strong` | `chunk_ids` non-empty **and** `evidence` present |

`evidence` is defined in spec §4 as a quotation from the cited chunk, so its presence is the
document's assertion that a chunk names this part. **D-008's validator checks that quotation
against real chunk text in Phase 3 and may downgrade `strong` to `weak`.** Parse states the
claim; the corpus check verifies it. If the architect wants the ruling's literal definition
instead, it can only live in Phase 2B/3 where chunk text exists, and `provenance_strength`
would then be absent at parse rather than provisional.

**Consequence:** all three golden specs are uniformly `weak` today — D-003's `["golden"]`
sentinel cites without quoting. Phase 2B task 2B.11 backfills real ids and real evidence, at
which point they become `strong`. A test pins that, so the backfill is visible when it lands.

---

## D-026 — Parent relations are classified; rotated parents are warned, never forbidden

**Status:** Accepted (architect rulings 11 and 12) · **Phase:** 1 · **Supersedes** D-024's threshold

D-024 compared axis-aligned bounding boxes and fired on **100% of the legitimate cases** in
the golden specs. A warning channel that is noisy on day one is ignored by day three, and it
pre-fills the curation gate with false positives.

**Two changes, in order.**

1. **Containment is measured against real geometry.** Both false positives were spheres, where
   an AABB over-reports badly — the box around a sphere is ~1.9x its volume. Child vertices
   are now sampled and tested against the parent's actual solid, analytically for sphere, box,
   cylinder, cone, capsule and torus, falling back to the AABB only for the swept and revolved
   types (tube, lathe, extrude) where there is no cheap closed form.
2. **The relation is classified, not scored.** "How much of the child is inside" cannot
   distinguish an envelope from a mistake. Measuring containment *both ways*, plus the volume
   ratio and the surface gap, separates four legal arrangements from the one that is wrong:

   | relation | test | treatment |
   | --- | --- | --- |
   | `contained` | child >= 90% inside parent | silent |
   | `surrounds_parent` | parent >= 75% inside child, child larger | silent |
   | `surface_attached` | child < 20% of parent's volume, touching | silent |
   | `adjacent` | surface gap <= 1x the child's own size | silent |
   | `detached` | none of the above | **warns** |

**`adjacent` is not threshold-tuning.** Branching anatomy parents by connectivity: a dendritic
branch joined end-to-end to its trunk has a perfectly clear relation while being nowhere
inside it. The neuron's 39 parented pairs are 20 `adjacent`, 11 `surface_attached`, 8
`contained` — the classification is *describing* a real authoring pattern, not excusing one.
That pattern is worth an architect ruling in its own right: **D-017's "is contained by" does
not cover branching topologies**, and the exploded view depends on that parenting to carry
subtrees correctly.

**Result: zero warnings across all four shipped specs**, with the warning verified still to
fire on a genuinely detached child (a negative control in `containment.test.ts`).

**Ruling 11 — the prohibition is reversed.** Phase 1 reported "the generator now refuses
rotated/scaled parents". To be exact about what that was: a single `assert` in
`packages/scenespec/fixtures/generate_stress.py`, the build script for the stress fixture.
**Nothing in the compiler, validator or schema ever prohibited it,** and the Phase 3 generator
does not exist. The assert is removed. Rotating a parent to carry its subtree is correct
scene-graph behaviour and a legitimate authoring tool; the axon hillock was an authoring
error, not a semantic one. The compiler now emits `rotated_parent` and
`non_uniform_scaled_parent` warnings — surfaced, never blocking. Uniform scale does not warn:
it carries a subtree cleanly.

---

## D-027 — Framing is bounds-derived; shelled topics open cut away

**Status:** Accepted (architect ruling 9) · **Phase:** 1

The stress fixture found this: the neuron's first `camera_hint` was authored in the shape of a
1-unit topic and cropped a 6-unit assembly at both ends. Every golden spec happens to be about
one unit across, so an authored distance looked correct right up to the first topic that was
not — and Phase 3 will generate topics of every size.

**The rule, as implemented:**

1. Fit the scene's bounding **sphere**, not its box. A box's fit depends on which way the
   scene is turned, so orbiting would push the model out of frame; a sphere is
   rotation-invariant and the framing holds at every angle.
2. `camera_hint` supplies the **direction**; the **distance is always derived**. That keeps
   the authored viewpoint — a real editorial choice — while removing the one number an author
   cannot get right without knowing the final bounds.
3. `look_at` is the bounding-sphere **centre**, not the origin. A neuron's mass sits well off
   the origin.
4. The fit uses the smaller of the vertical and horizontal half-angles, so a portrait viewport
   fits on width. Ignoring that crops on phones (Phase 4's mobile QA).

**Cutaway default.** A **shelled** topic — one whose largest part encloses >= 50% of the
others — shows nothing but its outer shell from outside, so it opens cut away. Measured from
geometry via the same machinery as D-026, not guessed from the topic name, so it stays correct
for topics that do not exist yet. Measured: `animal_cell`, `earth_layers` and `human_eye` are
shelled; `neuron` is not.

**Material audit.** The sclera rendered pink. Its colour `#f6f2ea` was a correct near-white —
the fault was `opacity: 0.16`, letting the choroid `#9a4a4a` and retina `#ea7f7c` behind it
show through. The audit found the same pattern across all three specs: **opaque solids had
been made transparent as a substitute for cutaway.** Six values corrected in the specs, not
the compiler — sclera 0.16 to 0.97, choroid 0.55 to 1.0, retina 0.8 to 1.0, crust 0.45 to 1.0,
upper mantle 0.7 to 1.0, lower mantle 0.9 to 1.0. Genuinely transparent structures (vitreous
and aqueous humour, cytoplasm, cell membrane, cornea, lens) were left alone. The cutaway
default is what makes opacity affordable.

---

## D-028 — Deterministic label layout, and the capture path splits in two

**Status:** Accepted (architect rulings 7 and 8) · **Phase:** 1

**Ruling 7 — two variants per view.** In Phase 3 these captures are the VLM critic's input,
and label collisions are the most visually wrong thing in a labeled frame. A critic given one
spends both of D3's repair rounds on typography while structural errors pass unexamined. So
`capture()` emits **unlabeled** (critic: geometry, occlusion, spatial relationships) and
**labeled** (human curator: naming, coverage, alias correctness). The variant is always named
in the filename — an unlabelled filename would make a critic input indistinguishable from a
human one at a glance.

**Ruling 8 — layout, not billboards.** The layout is a **pure function** of screen-space
facts, with no three.js and no DOM, so it is unit-testable without a browser and produces the
same frame every time — which byte-stable replay needs (3.7). It provides leader lines,
screen-space collision resolution by displacement over a fixed candidate-offset ladder,
depth-tested anchors, and dropping by `importance` lowest-first when space runs out. **This is
the first consumer of `importance`**, which D-006 reserved with no behaviour.

Two corrections found while building it, both of which had silently blanked labels:

- **Transparent parts must not occlude.** The raycaster has no notion of transparency, so a
  soma at 0.45 opacity blanked every organelle plainly visible inside it.
- **The raycaster ignores clipping planes.** Clipping is per-fragment on the GPU; the
  raycaster is a CPU intersection test. In cutaway mode every interior part was reported as
  occluded by the shell that had just been cut away — `human_eye` placed 1 label of 12 and
  `earth_layers` placed 0 of 5, both while plainly visible on screen.

**A third instance of the over-specification trap.** `ShotRequest` pinned `cutaway=0` on every
capture URL, so D-027's derived default could never fire in a capture and every gate image
silently showed the non-default path. `cutaway` is now tri-state, with `None` meaning "do not
say". This is the same failure as the Phase 1 outage and as ruling 9's `camera_hint`: **a
harness that pins every option cannot exercise behaviour that only happens when one is
absent.**

---

## D-029 — Corpora are content-addressed and ownerless; access is by grant

**Status:** Accepted (architect ruling, Phase 2 amendment) · **Phase:** 2A · **Amends** D-011

Recorded now, implemented in Phase 2A. Content-hash dedupe requires shared corpora; D-011 puts
`owner_id` on `corpora`. Those are incompatible.

**Decision:**
- `documents` stays owned (`owner_id NOT NULL`) — it is the upload record.
- `corpora` becomes **ownerless and content-addressed**, keyed by a hash of the raw file
  bytes, holding parsed content and embeddings. `owner_id` is dropped.
- New `corpus_grants` (`owner_id`, `corpus_id`, `granted_at`). **Access is by grant, never by
  ownership.**
- `qa_cache_meta.corpus_id` stays NOT NULL. D-007 holds; the cache is shared by design.

**Why shared caching is not a privacy hole.** Sharing is keyed on a hash of the raw bytes, so
**byte-identical files dedupe and nothing else does.** A private document has a unique hash
and is structurally isolated with no special-casing, no allow-list and no exception path —
there is no code that could leak across non-identical content, because there is no code that
relates non-identical content. Two users sharing a cache entry is proof they uploaded the same
file. This is worth stating explicitly because shared caching *sounds* alarming until the
impossibility is shown rather than asserted.

**Consequence:** the Phase 0 owner-scoping assertion changes meaning. It becomes "owner A
cannot read a corpus they hold no grant for", and the registry test changes membership —
`corpora` leaves the owner-scoped set, `corpus_grants` joins it.

---

## D-030 — Provenance strength has four states, and only two are knowable at parse

**Status:** Accepted (architect ruling) · **Phase:** 1 · **Refines** D-025

D-025 derived `strong` at parse from the presence of an `evidence` quotation, on the
grounds that Phase 3's D-008 check would downgrade it later. **The architect rejected that,
and was right to.** A field named `provenance_strength` reading "strong" when nothing has
read the chunk text is fabricated confidence — the exact failure D-025 exists to prevent —
and a downstream downgrade does not help, because every consumer between parse and that
check sees an unearned claim.

**Decision: the uncertainty is part of the type.**

| state | knowable at | meaning |
| --- | --- | --- |
| `none` | parse | `chunk_ids` is empty; nothing in the chapter is cited |
| `unverified` | parse | `chunk_ids` is non-empty; the text has not been examined |
| `weak` | 2B/3 | chunks were retrieved, none of them names the part |
| `strong` | 2B/3 | at least one cited chunk names the part |

Parse may emit **only** `none` or `unverified`. Emitting `weak` or `strong` at parse is a
**validation error**, not a convention: `assertParseTime` / `assert_parse_time` turn it into
a parse issue on both stacks, because typing alone would not catch a value arriving from
JSON, from storage, or from a future resolver that runs too early.

**`evidence` is deliberately not consulted.** A quotation the author supplied is still the
author's claim about a chunk nobody has read. It becomes evidence of anything only when
D-008 compares it against the cited chunk's real text.

**This is also a product distinction, not just a correctness one.** "We checked and found
nothing" (`weak`) and "we have not checked" (`unverified`) are different things to show a
student, and the old three-state enum could not express the second.

**Consequence:** the golden specs are uniformly `unverified` — D-003's `["golden"]` sentinel
cites a reserved id. Phase 2B task 2B.11 backfills real ids, and the D-008 check resolves
them. A test pins that, so the transition is visible when it lands.

---

## D-031 — `parent_id` is a scene-graph relation, not a semantic claim

**Status:** Accepted (architect ruling) · **Phase:** 1 · **Supersedes** D-017's semantics

D-017 said `parent_id` encodes containment. The neuron stress fixture disproved it: 20 of
its 39 parented pairs are `adjacent` and 11 are `surface_attached`, because a branching
structure parents by **connectivity** — which is precisely what makes its exploded view
carry each subtree correctly. Forcing containment semantics would either break the
explosion or fill the warning channel with correct structures.

**Definition, replacing D-017's:**

> `parent_id` means: **this part inherits its parent's transform and moves with it under
> explode.** Nothing more.

The spatial relation — `contained`, `surrounds_parent`, `surface_attached`, `adjacent`,
`detached` — is **derived** by the compiler's classification (D-026), never asserted by the
author.

**That separation is the point.** A derived property can disagree with the structure and
say so; an asserted one cannot be wrong by construction. It is what makes the warning
meaningful rather than tautological.

**Consequences implemented:**
- `adjacent` and `surface_attached` are **fully legal parentings**, not tolerated
  exceptions.
- `detached` remains the only warning: it means the transform relation has no spatial
  justification at all.
- The derived relation is **attached to each compiled part** (`CompiledPart.containment`),
  so the curation gate and the Phase 3 repair prompt read it rather than reimplementing the
  geometry tests. It lands on the compile result rather than the parse result because it
  requires built geometry — parse has no meshes, and the Python stack has no compiler.
- D-017 amended in place with a pointer here; its *explosion* ruling is unaffected, only
  its justification.

---

## D-032 — A transparent shell is not a shell

**Status:** Accepted · **Phase:** 1 · **Refines** D-027

D-027 defaulted a topic to cutaway when its largest part enclosed most of the others.
`animal_cell` qualified and lost 6 of 13 labels to clipping — a 46% drop against the
neuron's 5%, which the architect flagged as an outlier worth confirming rather than
assuming.

**Measured, with cutaway forced both ways:**

| topic | cutaway on | cutaway off | shell |
| --- | --- | --- | --- |
| `human_eye` | **12 / 12** | 1 / 12 | sclera at 0.97 |
| `earth_layers` | **5 / 5** | 0 / 5 | crust at 1.0 |
| `animal_cell` | 7 / 13 | **13 / 13** | membrane at 0.18 |

Two things follow. First, the transparency raycast fix **does** apply to `animal_cell` —
with cutaway off it places all 13, so the membrane and cytoplasm correctly occlude nothing.
The 6 drops were purely clipping: those organelles sit at positive *z* and the plane keeps
*z ≤ 0*. Second, `animal_cell` is the only topic whose shell is see-through, so cutting it
away **costs six labels and reveals nothing**.

**Decision:** `isShelled` additionally requires the enclosing part to be opaque
(opacity > 0.85). A see-through shell is not a shell. All four topics now place every
visible label with cutaway unspecified: 13/13, 12/12, 5/5, and 38/40 for the neuron whose
two drops are genuinely behind opaque geometry.

---

## D-033 — Standing engineering rules live in `agents.md`

**Status:** Accepted (architect ruling) · **Phase:** all

R1 — *a parameter with a default must be able to say "unspecified", and something must
exercise the unspecified path* — is now a project-wide rule in `agents.md`, alongside three
others drawn from defects this project actually hit (R2 guards, R3 verdict-vs-behaviour,
R4 report what was not done).

**Audit result, R1.** One further live instance, now fixed: **`frameScene` takes an
`aspect` with a default of 1280/900, and the Viewer could only pass `angle`** — the canvas
size is not known until r3f has mounted. So the default was the only value the function
ever received, and a portrait phone would have been framed as landscape and cropped. A
`CameraRig` inside the Canvas now reframes with the live aspect, keyed on spec, angle and
aspect so a resize or orientation change re-fits while orbiting is left alone. This would
have surfaced as a mystery in Phase 4's mobile QA.

Two lesser instances recorded but not changed: the render route pins `shot`, `explode` and
`explodeMode` on every request (their defaults are unreachable from that path, though the
values agree), and `Settings.from_env`'s `AAKAR_PROVIDER_MODE` default is never exercised
because the Makefile and CI both set it explicitly. Both are noted here so a future change
to either default is known to be untested from those paths.

---

## D-034 — Ingest is asynchronous; rejection is not

**Status:** Accepted (architect ruling) · **Phase:** 2A

`max_ocr_pages` of 40 at ~25 s/page is ~17 minutes for one upload. No HTTP request survives
that, so ingest cannot be request/response — and the upload route could not have been built
as one. This was missing from the Phase 2 amendment and is mandatory given the approved
limits.

**The split that matters.** Every boundary check runs **synchronously**, before the
response: size, page count, OCR page count, encryption, the per-owner daily quota, and the
global queue bound. Only accepted work is queued. A rejection that arrives seventeen minutes
later is a worse product than one that arrives immediately, and an unbounded queue turns a
rejection into a resource commitment that merely happens later.

**Implemented:** `ingest_jobs` (queued/running/succeeded/failed/rejected, with
`pages_done`/`pages_total`, timestamps and `failure_reason`); `POST /ingest/upload` returning
**202 Accepted** with a job id — not 200, because nothing has been parsed and 200 would say
otherwise; `GET /ingest/jobs/{id}` owner-scoped, **404 not 403** for another owner, because a
403 confirms the id is real; and a worker in `aakar/ingest/worker.py` that runs in a separate
process.

**Progress is real.** `pages_done` is written as pages complete, never interpolated from
elapsed time. A bar that moves while nothing happens is worse than no bar.

**Found while building:**

- **The queue was not actually FIFO.** `created_at` has one-second resolution, so jobs
  submitted in the same second tied, and the tiebreak was `id` — a random uuid. Ordering is
  now `created_at, rowid`, which is monotonic in insertion order. The old behaviour was
  arbitrary under exactly the load where FIFO matters.
- **A connection opened by a sync FastAPI dependency is used from a different thread** than
  an `async def` endpoint body, because the dependency runs in the threadpool. `connect()`
  now passes `check_same_thread=False`. This is a production concern; it surfaced in a test
  only because that is where an async endpoint first existed.

---

## D-035 — The worker is a persistent process; this component cannot be serverless

**Status:** Accepted · **Phase:** 2A · **Consequence of** D-034

Recorded so the deployment choice is made with this in mind rather than discovered by it.

The ingest worker does minutes-long, CPU-bound work that outlives any request. **Serverless
is out for this component.** The API can still be deployed however one likes; the worker
needs a process that stays alive, with disk access to the uploaded file.

Two further consequences the architect flagged, recorded here so they are not rediscovered:

1. **Degraded mode must distinguish "worker unavailable" from "budget exhausted."** They are
   different causes with different recoveries — a stalled worker is an operational problem
   that resolves without the user doing anything, while an exhausted budget needs an
   explicit decision. Implemented in 2B as separate `DegradedReason` values with separate
   messages.
2. **A "processing" state now exists in the product**, and the UI design does not account for
   it. Recorded, not built: the viewer has no notion of a document that exists but is not yet
   readable.

---

## D-036 — LightningParse is available; 2A.5 is answered by measurement

**Status:** Accepted · **Phase:** 2A · **Corrects** the Phase 2A report

**My Phase 2A report was wrong.** It said LightningParse was "not installed and not on
PyPI". It *is* on PyPI, as `lightningparse`, and the source is `ShivamMalge/LightningParse`.
The error was method: `importlib.find_spec` only sees *installed* packages, and I drew a
conclusion about PyPI from that plus one failed download command. Pinned at **0.4.1**
exactly — a `3.1.0` also exists on PyPI, out of sequence with the 0.x line, so an unpinned
range could resolve to it silently.

**2A.5, answered by running it. There is no warnings array in 0.4.1.** The amendment's
premise does not hold for this version. What it emits:

```
{"metadata": {"tier", "page_count", "parse_time_ms"},
 "pages": [{"page_num", "blocks": [{"type","text","spans","bbox","section_id","source"}]}]}
```

| signal | granularity | observed |
| --- | --- | --- |
| `metadata.tier` | per **document** | `digital` \| `scanned` |
| `block.source` | per **block** | `digital` |
| `block.section_id` | per **block** | `header`, … |

So the finest available granularity is **per block, which is finer than per chunk** — a chunk
is built from blocks. `source` is stored per chunk at block granularity; `metadata.tier` is
stored per document on `documents.parse_tier`.

`warning_scope` now defaults to **`none`** — a measured fact about 0.4.1, not the hedge it
was in 2A. `warnings_json` and `warning_scope` are kept for the day the parser gains a
warnings array, so a future version cannot silently reinterpret an existing column.

**One further measured behaviour, useful at the boundary:** a PDF with no text layer reports
`tier: "scanned"` and produces **zero blocks**. LightningParse says so itself, cheaply.

Chunking is one chunk per block for now. Blocks already carry `section_id`, so they are
heading-aware, and merging them would coarsen the `source` signal 2A.5 exists to preserve.
Whether to merge short adjacent blocks is a retrieval-quality question, and it should be
settled against measured hit rates rather than guessed at.

---

## D-037 — Global ingest bounds

**Status:** Accepted (architect ruling) · **Phase:** 2A

Per-owner quotas stop one user hurting everyone; they do nothing about fifty users doing it
collectively. At the approved 400 pages/day against a 500-account ceiling that is ~200,000
pages/day — roughly **1,400 CPU-hours**, about 58 machine-days of work per day.

| bound | proposed | reasoning |
| --- | --- | --- |
| `max_concurrent_ocr` | **2** | the binding resource is CPU and OCR is CPU-bound, so useful concurrency is bounded by cores, not patience. Raising it on a saturated machine does not add throughput — it lengthens every job at once, turning one slow upload into several |
| `max_queue_depth` | **50** | at 2 concurrent and a 17-minute worst case, a full queue is ~7 hours of backlog. Beyond that a queued job is indistinguishable from a lost one |

Queue-full is rejected **at submission**, with the current depth in the message so a retry is
informed. Both are configurable; both default low, because the cost of a too-low bound is a
visible rejection and the cost of a too-high one is a queue nobody drains.

**The bound counts every owner**, which is the entire point — no single owner is doing
anything wrong when it trips.

---

## D-038 — Tesseract is a deployment requirement; OCR runs at ~3.8 s/page, not 25

**Status:** Accepted · **Phase:** 2A · **Corrects** D-036 and D-037's arithmetic

The architect asked which of three things was true about OCR in LightningParse 0.4.1. The
answer is **(b)**, and establishing it corrected two of my own earlier claims.

**Evidence** (`evidence/phase2c/ocr-investigation.txt`):

1. `parse_pdf(path)` takes **only a path** — OCR is not behind a parameter, so (a) is out.
2. The package README: *"OCR (Tier 2) additionally requires Tesseract on your `PATH`. It is
   invoked only when a page has no extractable text."* Two tiers, selected **per page**;
   documents containing both report `tier: "mixed"`.
3. Tesseract **5.4.0 is present on this machine**, at `/c/Program Files/Tesseract-OCR/`.
4. A genuine scan — a text PDF rasterised to JPEG at 150/300 dpi and re-wrapped — parses
   with `tier: "scanned"` and blocks carrying **`source: "ocr"`**, text extracted correctly.

**My earlier claim that a text-layer-free PDF "produces zero blocks" was wrong**, and wrong
in an instructive way: I had tested with `pypdf.add_blank_page`, which makes a genuinely
empty page. A blank page correctly yields nothing. That was never evidence about OCR, and I
generalised from it.

### The 25 s/page figure does not hold

| pages | dpi | wall s | **s/page** | tier |
| --: | --: | --: | --: | --- |
| 1 | 150 | 3.78 | **3.78** | scanned |
| 3 | 150 | 11.35 | **3.78** | scanned |
| 1 | 300 | 3.33 | **3.33** | scanned |
| 3 | 300 | 10.54 | **3.51** | scanned |

**3.3–3.8 s/page**, stable across page count and resolution — roughly **6.6× faster** than
the figure every ingest limit was justified against. Restated consequences:

| claim as written | corrected |
| --- | --- |
| 40 OCR pages ≈ 17 min | ≈ **2.5 min** |
| 400 pages/day/owner ≈ 2.8 CPU-hours | ≈ **25 CPU-minutes** |
| 500 accounts ≈ 1,400 CPU-hours/day | ≈ **211 CPU-hours/day** |
| queue depth 50 ≈ 7 hours backlog | ≈ **1 hour** |

**The numbers are kept, the rationale is corrected.** Two reasons not to relax them to
match:

1. **The measurement is a floor, not a ceiling.** The scan was synthetic: clean, high
   contrast, upright. Tesseract's runtime varies widely with real degradation, and the
   package's own README warns about "heavy combined distortion". Planning against the best
   case would be over-fitting to it.
2. A limit that must be raised is a one-line change; a limit that must be lowered is
   discovered under load.

**One recommendation, pending approval: raise `max_ocr_pages` from 40 to 80.** A scanned
textbook chapter runs 20–60 pages, so 40 currently rejects a legitimate primary case — and
at the measured rate 80 pages is ~5 minutes, which the queue absorbs. Left at 40 until
confirmed, since 40 was explicitly approved.

### Deployment requirement

**Tesseract on `PATH` is now a deployment requirement, not merely a library dependency.**
It cannot be expressed in `pyproject.toml`. Combined with D-035 (the worker must be a
persistent process), the ingest component needs a container or host that carries a
system binary — which rules out most managed Python runtimes as well as serverless.

Without it, LightningParse raises `OcrMissingDependencyError`, which
`aakar/ingest/parser.py` already translates into an explicit rejection addressed to the
operator rather than to the uploader. So a missing Tesseract degrades to "scanned uploads
are refused with a reason", never to "scanned uploads succeed into an empty corpus".

### A corpus with zero chunks is never created

Independently of OCR, and worth having regardless: a parse that yields no chunks now
**fails the job explicitly** with `no_extractable_text`, rather than succeeding. An empty
corpus looks ingested, retrieves nothing, and answers every question with "your chapter
does not cover this" — indistinguishable, to the student, from a chapter that genuinely
says nothing.

---

## D-039 — `metadata.warnings` exists, and is per-document

**Status:** Accepted · **Phase:** 2A · **Corrects** D-036

D-036 said LightningParse 0.4.1 emits no warnings array. **Wrong.** `metadata.warnings` is
an *optional* key, present only when the parser has something to report; every document I
had measured was clean, so I read absence-in-this-output as absence-from-the-schema. It
appears immediately on a document with a problem:

```
metadata keys: ['page_count', 'parse_time_ms', 'tier', 'warnings']
warnings: ["Page 1: content stream uses unsupported filter 'JBIG2Decode', falling back to OCR"]
```

**So the answer the amendment asked for is: warnings are PER-DOCUMENT.** Each entry names
its page in prose, but the array is a flat list of strings rather than structured per-page
data — attributing one to a chunk would mean parsing that prose, which is a provenance
claim the parser never made.

**Stored accordingly:** `documents.parse_warnings_json` holds the array; `chunks.source`
(per block, `digital` | `ocr`) remains the finest per-chunk signal, and
`chunks.warning_scope` records `document` when the document carries warnings, so the UI can
say what a warning actually covers.

---

## D-040 — The derived relation comes from `compile()`, carried on the sentinel

**Status:** Accepted (architect ruling) · **Phase:** 1–3

I recommended the screenshot harness return the relation alongside the capture. The
architect accepted the mechanism and rejected the timing, on my own objection: coupling it
to a successful render means a spec too broken to render yields no diagnosis **precisely
when the repair loop needs one**, and structurally broken specs are the main thing that
loop exists to fix.

**Decision:** the relation is emitted from `compile()`, *before* the frame is drawn, and the
sentinel carries it out — `data-relations` (partId, parentId, relation, and the three
measures) and `data-warnings` alongside the existing label counts.

This keeps both properties intact: **single derivation** (D-026 — one implementation, so
two stacks cannot disagree about whether a spec is broken) and **single capture path**
(D-009 — no second Node entry point to drift from the viewer). A render failure now yields
a relation *plus* a render error, which is a far better critic input than nothing.

---

## D-041 — The cache threshold defaults conservative, and is config

**Status:** Accepted (architect ruling) · **Phase:** 2B

The measured table showed 0.85 was also false-hit-free on a synthetic embedder. **0.92 is
chosen anyway.**

**Rationale, as ruled:** a false hit is a correctness failure that reaches a student as a
confidently wrong answer; a low hit rate is only cost. Those are not symmetric, and cost is
the one you can afford to be wrong about.

`AAKAR_CACHE_THRESHOLD` makes it **config, not a constant**, so the re-measurement against
the real embedder can land without a code change. That re-measurement is a gate item in
whichever phase introduces the real embedder, and it uses the same two-sided method —
**false-hit count included, never a hit rate alone**.

---

## D-042 — Per-job wall-clock timeout: 1800 s

**Status:** Accepted (architect ruling) · **Phase:** 2A

`max_ocr_pages` bounds **pages**, not **time**, and the 3.3–3.8 s/page measurement came from
a clean synthetic scan while the parser's README warns about degraded ones. A pathological
document could hold one of two worker slots indefinitely, and one stuck job halves capacity.

**Default 1800 s (30 minutes).** That is ~6× the clean worst case for a maximum-size job
(80 OCR pages at 3.8 s/page ≈ 5 minutes). The headroom is deliberate in one direction and
bounded in the other: Tesseract on a skewed, noisy, small-type scan runs several times
slower, and **killing legitimate degraded work is a failure the uploader cannot fix**, while
a pathological job is capped at half an hour rather than "hours". Configurable, and it
should be lowered once real-world timings exist.

**Implemented as a killable subprocess, not a thread.** `lightningparse.parse_pdf` is one
blocking call into Rust. It releases the GIL, so a thread stays responsive — but a thread
cannot be *killed*, so abandoning one would leave the work running and free the slot in name
only. `parse_isolated` runs `aakar.ingest._parse_subprocess` under `subprocess.run(timeout=)`,
which genuinely terminates it.

**On expiry:** the job is marked `failed` with reason `timed_out:`, **distinguished from a
parse failure**. The document may be perfectly valid and merely slow, so "could not be read"
would be a false statement — and only a timeout is worth retrying on a quieter system.
Nothing is written, because chunks are stored after the parse returns, so there is no
partial corpus. Same rule as `no_extractable_text`: a half-ingested chapter that looks
ingested is worse than a clean failure.

`max_ocr_pages` raised **40 → 80** on the same ruling: 40 rejected a scanned chapter of
40–60 pages, which is a primary case.

---

## D-043 — Embedding model and dimensionality, fixed before the collection exists

**Status:** Accepted · **Phase:** 2C · **One-way door**

Recorded **before** the Qdrant collection is created, as required. Changing dimensionality
later means re-embedding every corpus, and with content-addressed corpora (D-029) that is
every corpus every owner shares.

> ### AMENDED 2026-08-30 — the model originally pinned here was already dead
>
> This entry first pinned **`text-embedding-004`**. That model was **shut down on
> 14 January 2026** — *seven months before it was pinned here.* Not deprecated, not
> scheduled: gone.
>
> **Why nothing caught it.** Every ingest in this project has run on the replay embedder,
> so no model name had ever been resolved against the provider. The first real call would
> have been the first 404 — in production, on a student's upload, at the moment the whole
> pipeline was finally being used for real.
>
> **The pattern, which matters more than the fact.** Pinning protects against *drift*: the
> model changing under you. It does nothing about a pin to something that no longer exists,
> and from inside a replay-mode test suite those two are indistinguishable — both produce a
> green suite. I had reasoned carefully about dimensionality being a one-way door while
> never checking that the door led anywhere. D-045 adds the check.
>
> The corrected pin is below. The 768-dimension collection width, `ensure_collection`'s
> mismatch refusal and the dimension-matched replay embedder all survive unchanged, because
> 768 is a recommended MRL tier on the new model too — which is why this was the cheapest
> possible moment for the correction: nothing was embedded yet.

| | value | note |
| --- | --- | --- |
| model | **`gemini-embedding-001`** | stable, no announced shutdown (verified 2026-08-30) |
| **dimensions** | **768** | via `output_dimensionality`; native is 3072 |
| distance | cosine | |
| normalization | **manual L2, by us** | see below — this is the trap |
| task type | `RETRIEVAL_DOCUMENT` indexing, `RETRIEVAL_QUERY` querying | |
| collection | `chunks` | unchanged |

### MRL truncation returns UNNORMALIZED vectors — confirmed from the docs

The provider's embeddings documentation states it directly: only the default 3072-dimension
output is normalized for you, and *"if you are using `gemini-embedding-001`, you must
manually normalize non-3072 dimensions"*, with an L2 example. `gemini-embedding-2`
auto-normalizes truncated dimensions; `-001` does not.

**Why this would have been invisible.** Cosine on an unnormalized vector does not fail. It
returns a number in [-1, 1] — just the wrong one, weighted by magnitude. Retrieval quietly
degrades, the relevance floor starts refusing questions the chapter does cover, and every
symptom points at "the embedder is weak" rather than "we skipped a division". It is
precisely the class of bug that survives to production because nothing ever raises.

**Implemented as unconditional.** `l2_normalize` is applied to every vector from every
source, not behind a model check. Normalizing a unit vector is a no-op, so there is no
branch to get wrong — and a future model that changes its normalization behaviour cannot
silently break this.

### `gemini-embedding-2` considered and rejected — for now

The deprecation page names `gemini-embedding-2` as 004's replacement, and it would remove
the manual-normalization footgun entirely by auto-normalizing truncated dimensions. It is
listed as **`gemini-embedding-2-preview`**, and a preview model is the wrong thing to put
behind a one-way door: re-embedding every shared corpus is the exact cost this decision
exists to avoid paying twice. Revisit when it reaches stable.

**Why 768 and not a reduced dimension.** `text-embedding-004` emits 768 natively. Truncating
would save index memory at a corpus size that does not need saving, and would make the
stored vectors incomparable with anything re-embedded later at full width. The saving is
hypothetical; the incompatibility would be permanent.

**Cosine, not dot product.** The cache already compares with cosine (`rag/cache.py`), and two
similarity measures in one system is a bug waiting to be written — a threshold calibrated
against one silently means something else against the other.

**The replay embedder produces 768 dimensions too.** This matters more than it looks: a test
collection built at the stub's natural width would exercise a collection shape production
never uses, and the first real ingest would be the first time the real shape ran. The
deterministic embedder used in replay is dimension-matched on purpose.

**Recorded limitation.** The vectors this project can produce today are *not* from
`gemini-embedding-001` — there is no API key, and CI runs in replay. Everything below the
provider abstraction is the real path; the vectors themselves are not. Any threshold
calibrated on them measures the **method**, not the number (D-041).

---

## D-044 — OCR text is weaker evidence; source is a second axis, not more states

**Status:** Accepted (architect ruling) · **Phase:** 2C

`chunks.source` (`digital` | `ocr`) is a **confidence** signal, not just provenance
metadata: OCR misreads are silent and produce plausible wrong words, so a citation resolving
to an OCR'd chunk is less trustworthy than one resolving to extracted text.

**Proposal, as asked: do not collapse it into the four states.** Keep
`{none, unverified, weak, strong}` and carry `source` **alongside** it.

The two answer different questions:

* **strength** — *does the chapter assert this part exists?* (D-030)
* **source** — *how reliably did we read the chapter?*

They are independent. A part can be `strong` because three chunks name it while every one of
those chunks was OCR'd; that is a strong claim read through an unreliable lens, and it is
genuinely different from both `weak/digital` and `strong/digital`.

**Collapsing them multiplies the enum to six** (`strong_digital`, `strong_ocr`, `weak_ocr`, …)
and every consumer then switches on six cases to ask a question about one axis. Worse, it
makes "strong regardless of how we read it" inexpressible, which is exactly the query the
curation gate wants when ranking what a human should check.

**Represented as** `ResolvedProvenance(strength, source, chunk_ids, ...)`, where `source` is
`digital` | `ocr` | `mixed` — `mixed` when the supporting chunks disagree, rather than
picking one arbitrarily. A single `display_confidence` property combines them for the one
place that wants a single word, so the combination lives in one function rather than in
every caller.

---

## D-045 — Every model pin is validated at boot; two of three were already dead

**Status:** Accepted (architect ruling) · **Phase:** 2C · **Audit result**

The architect flagged one dead pin. Checking every one, as instructed, found **two**.

| setting | was pinned to | status | now |
| --- | --- | --- | --- |
| `AAKAR_EMBED_MODEL` | `text-embedding-004` | **shut down 2026-01-14** | `gemini-embedding-001` |
| `AAKAR_MODEL` | `gemini-2.0-flash` | **shut down 2026-06-01** | `gemini-3.6-flash` |
| `AAKAR_VLM_MODEL` | `gemini-2.0-flash` | **shut down 2026-06-01** | `gemini-3.6-flash` |
| `AAKAR_ANSWER_MODEL` | falls back to `AAKAR_MODEL` | inherited the same dead pin | inherits the fix |

Verified 2026-08-30 against the provider's deprecation and model pages. `gemini-2.0-flash`
is listed as *"Shut down"*, with `gemini-3.6-flash` named as its replacement. So **every
model this project would ever have called was retired**, and the generation model had been
dead for three months.

`gemini-3.6-flash` rather than the newer `gemini-3.7-flash`: 3.6 is the provider's own
stated migration target for 2.0-flash, it is stable, and it is multimodal — which the VLM
critic (D3) needs. Moving to 3.7 is a deliberate upgrade, not a repair, and mixing the two
would confuse a forced correction with a chosen improvement.

### Why nothing caught it, and what now does

Every test in this project runs in `replay`, against a stub provider or the local embedder.
**No model name had ever been resolved against the provider**, so a pin to a live model and
a pin to a retired one produced identical green suites.

Two layers, because they fail in different circumstances:

1. **`RETIRED_MODELS`** — a local registry with shutdown dates, checked inside
   `Settings.from_env()`, so it runs at **boot in every mode with no network**. This is the
   layer that catches what actually happened, and it works in CI where there is no key. It
   requires maintenance, and that is the point: a retirement is a fact about the world that
   someone has to write down.
2. **`assert_live_models`** — asks the provider which models a key can reach. Only usable in
   `live`/`record`, which is exactly why layer 1 has to exist: a check needing a key would
   never have run here.

A future retirement is *allowed* until its shutdown date, so an announcement does not force
a migration on a schedule the provider did not set. `test_no_shipped_default_is_a_retired_model`
is the standing regression guard.

### The general lesson, recorded because it will recur

This is agents.md R1's shape in a new place. R1 says a default that is always overridden is
never exercised. Here a *pin* that is never resolved is never exercised — and the pin
existed specifically to make the dependency trustworthy. **A guard that has never been
executed against reality is indistinguishable from one that does not work**, which is R2,
arriving from a direction R2 did not anticipate.

---

## D-046 — Alias coverage is load-bearing for provenance; verify it in Phase 3

**Status:** Recorded, not built (architect instruction) · **Phase:** 3

Provenance resolution matches chunk text **whole-word** (D-030, 2C.6), so `iris` does not
match `irises`. That is the right trade — substring matching fires on `irishman`, and a part
promoted to `strong` by a coincidental prefix is the fabricated-confidence failure the whole
design exists to prevent. Inflected forms are reached through `aliases`, which is what D5
made them for.

**The consequence for Phase 3.** If the generator emits `"iris"` without `"irises"`,
provenance **under-reports systematically**: parts sit at `weak` while the chapter names
them plainly, the curation gate fills with parts that look ungrounded, and a human wastes
review time on a vocabulary problem that reads as an evidence problem.

The VLM critic — or a separate deterministic check, which is likely the better fit since
this is a text question and not a visual one — must verify **alias coverage against the
chapter's actual inflections** before completeness is judged. Recorded now so it is designed
in rather than discovered when the pilot batch's completeness numbers look inexplicably low.

---

## D-047 — Provenance must survive the citation line and the cache

**Status:** Built · **Phase:** 2D.1e

D-044 put `source` beside `strength` as a second axis and combined them in one place,
`ResolvedProvenance.display_confidence`. Building 2D.1e found two paths where that value
was correct and the student still could not see it.

**1. The citation line said nothing.** `Citation.render()` produced `[p. 543]` whether the
page had been extracted from a digital PDF or read by an OCR engine. An answer-level
qualifier tells a reader that *something* here is uncertain; it does not tell them *which
page to distrust*. With four digital citations and one scanned, that is the entire
question. OCR renders as `[p. 543, scanned]`. Still the label, never the index (D6).

**2. `display_confidence` read the wrong set of chunks.** `resolve()` reads its source axis
from the chunks that **name the part**, because that is the evidence the strength rests on.
What the student is *shown* is every retrieved citation — a superset. So an answer could
rest on digital evidence, put a scanned page in front of someone, and describe itself as
`strong`. `Answer.display_confidence` widens the source axis over the citations actually
shown. Wholly-OCR evidence keeps `(OCR)` rather than decaying to `(partly OCR)` because an
unrelated digital chunk was also retrieved: the claim still rests entirely on machine-read
text. The widening can only ever make a confidence more cautious.

**3. The cache dropped it entirely.** A cache hit rebuilds an `Answer` from stored JSON and
never re-resolves provenance, so the same answer read `strong (OCR)` when generated and
`unknown` once cached. **The OCR warning survived exactly until the question became popular
enough for a second student to ask it** — the worst possible schedule, since it disappeared
precisely as the number of people relying on it grew. `strength` is now stored with the
answer; `source` is re-derived from the stored citations rather than persisted, so it
cannot drift out of step with them. Rows written before this change restore no provenance
and report `unknown`, which is the honest reading — inventing `strong` for a row that never
recorded one would fabricate the confidence this axis exists to qualify.

**The shape, because it will recur.** A value can be computed correctly and still never
reach a reader. Each of these three was a *display* bug in a system whose entire product
claim is that the student can check the source. The general form: **a correctness property
that is only enforced at the point of computation is not enforced** — it has to be carried
through every path the value takes, and the cache is always one of those paths.

---

## D-048 — The golden set is PROPOSED until a human signs it, and the code enforces that

**Status:** Built · **Phase:** 2D.1a

`evals/golden-provenance/` ships `verified: false`. Every `supported_by` list in it was
proposed by the system it is meant to evaluate, and a golden set labelled by the thing it
evaluates measures self-consistency and calls it accuracy.

Three mechanisms keep that from being a comment nobody reads:

* `load_golden_set` marks everything `provisional` while the flag is false, and that flag
  rides through `FaithfulnessReport.provisional` into the printed report — so a number
  cannot escape its caveat by being copied out of a terminal.
* A set claiming `verified: true` with no `verified_by` is **refused**. That is worse than
  an unverified one: it looks like evidence and cannot be chased down.
* Page labels carry their own disclaimer. The chapter was retrieved as HTML, so its
  `page_label` values are assigned by section order rather than read from a PDF. The
  label-vs-index mechanism was proven in 2C against a real `/PageLabels` tree; this fixture
  is for faithfulness, not pagination, and says so in the file.

Scoped to 15 questions over 10 chunks on purpose. Verification is manual work with no
substitute, and **a set too large to hand-check is a set that will not be hand-checked.**

---

## D-049 — A cached answer must be field-for-field identical to a fresh one

**Status:** Built · **Phase:** post-2D.1, architect ruling

D-047 fixed a specific instance: `display_confidence` vanished on a cache hit. That was
found by looking, and looking does not scale — **anything computed at answer time and not
stored can vanish the same way, and every fresh-path test stays green while it does.** So
the instance is replaced by a property.

**The invariant.** For the same question against the same corpus, the answer the second
student receives is identical to the one the first received, field by field, except for the
handful of fields whose job is to differ.

**Enforced by inversion.** `ALLOWED_TO_DIFFER` lists the *exemptions* — `kind`,
`from_cache`, `similar_question`, `retrieval` — and the comparison is driven by
`dataclasses.fields(Answer)` plus every `property` on the class. A field added later is
therefore compared **by default**. Listing the fields to check instead would have meant a
new field silently uncovered, which is the failure mode this decision exists to close. A
second test strips the stored provenance and requires the comparison to fail, because a
comparison that has never caught a divergence has not been shown to work (R2).

### What it found immediately — including one I had reported as fixed

The first run diverged on three things, all from the same root:

| field | fresh | cached |
| --- | --- | --- |
| `provenance.source` | `ocr` | `mixed` |
| `provenance.naming_chunk_ids` | 1 id | `()` |
| `provenance.retrieved_chunk_ids` | 5 ids | `()` |
| **`display_confidence`** | **`strong (OCR)`** | **`strong (partly OCR)`** |

The last row matters most: **`display_confidence` was the field D-047 claimed to have
fixed, and it was still diverging.** D-047 stored `strength` and re-derived `source` from
the cached citations, reasoning that a derived value cannot drift from what it derives from.
The reasoning was sound and the premise was false — **the fresh path does not derive
`source` from the citations at all.** It reads it from the chunks that *name the part*, a
strict subset. The reconstruction was plausible, self-consistent, and a different value.

`naming_chunk_ids` and `retrieved_chunk_ids` were lost outright. Nothing reads them today;
the curation gate will.

**The fix** stores the whole provenance in one payload written once, and validates both
enums against their `Literal` members on the way back out rather than trusting JSON from the
database. Rows written before this report `unknown` — inventing `strong` for a row that
never recorded one would fabricate the confidence the axis exists to qualify.

**The general shape, because it is now the second instance.** Storing part of a value and
reconstructing the rest is not a saving; it is a second implementation of the derivation,
built from different inputs, that nothing compares against the first. Store the whole value
or recompute the whole value — never half of each.

---

## D-050 — DEFAULT_FLOOR raised to 0.45, interim and uncertified

**Status:** Built, **uncertified** · **Phase:** post-2D.1 · **Supersedes the value in 2C.3**

`DEFAULT_FLOOR` moves from 0.35 to **0.45**.

**The finding is not the number, it is that 0.35 was never measured.** It was picked by
judgement when the floor was built in 2C.3 and shipped as though it had been calibrated.
The 2D.1 sweep is the first time any value was tested against questions with known answers,
and 0.35 admitted **two of five hard negatives** on the golden chapter — questions the
chapter cannot answer, cleared to a confident cited answer assembled from irrelevant text.

**Why 0.45 despite the number not transferring.** The measurement is on a lexical embedder
and does not carry to a semantic one. The **asymmetry does**, and it is embedder-independent:
false coverage reaches a student as a fluent, cited, wrong answer about their own textbook,
while a false "your chapter does not cover this" costs only usefulness and is a true
statement they can act on. Those are not symmetric, so the tie is broken toward refusing.
Same reasoning as the 0.92 cache threshold (D-041). 0.45 is the lowest swept value admitting
zero false coverage.

**What it costs, stated rather than buried.** On the golden set, coverage falls from 100% to
80% — `q04` and `q08` stop clearing. On the five-sentence `test_retrieval` fixture the cost
is total: a directly-covered question scores about 0.43 there, so at 0.45 that corpus admits
nothing, and three `/ask` tests now pin the floor explicitly via `AAKAR_RELEVANCE_FLOOR`.
That is a property of a toy corpus scored by word overlap, not of the floor — but it is the
cost being accepted, and it is written down rather than absorbed.

**Uncertified.** To be replaced by 2D.2's measurement against `gemini-embedding-001`. Until
then `test_the_shipped_default_floor_both_admits_and_refuses` holds it to both halves of its
job on a real chapter — a floor at 1.0 refuses everything and would otherwise pass every
safety test written about it.

---

## D-051 — Selection methods are registered and certified, like embedders

**Status:** Built, **all methods uncertified** · **Phase:** 2D.1f · **No mechanism change**

The relevance floor was never a mechanism anyone chose; it was the first thing that worked,
and D-050 found its value had never been measured. 2D.1f makes the *mechanism* a choice
with the same shape as the embedder choice, so the next one is picked on evidence.

**Three methods, all `certified=False`:**

| method | rule | pool |
| --- | --- | --- |
| `absolute` | top-1 ≥ `DEFAULT_FLOOR` | **every** retrieved hit (production, unchanged) |
| `margin_top2` | top-1 − top-2 ≥ 0.10 | hits within 0.10 of the top |
| `margin_distribution` | top-1 ≥ 1.5 sd above the corpus mean | hits ≥ 1.5 sd |

**The guard.** `shipped_method()` raises `UncertifiedMethod` for anything not measured
against a real embedder; `resolve_method()` deliberately does not check, because a harness
that could only run trusted methods could never produce the evidence that makes one
trusted. Today `shipped_method()` refuses everything, which is correct — the production
path does not call it, and wiring one in is a ruling that follows 2D.2's measurement rather
than something an environment variable can do first.

**A method decides two things and both are reported.** `covered` (Rule 6) and the *pool* —
which chunks reach the prompt. They are not separable: a rule confident enough to answer is
asserting which evidence is good. Reporting only coverage would hide that
`margin_distribution` reaches 80% coverage on a mean pool of **1.1 chunks**, which is not
better retrieval, only quieter.

**`absolute`'s pool is every hit, and that is a finding in itself.** Production passes all
eight retrieved chunks to the prompt regardless of score, so a chunk at 0.02 is handed to
the model alongside one at 0.9. The floor gates *whether to answer* and does nothing about
*what the answer is built from* — a gap neither D-050 nor the 2C design noticed, because
nothing had ever reported pool composition.

**Faithfulness is measured under each rule** by rewriting each fixture's markers from its
own passage list into the method's pool. A fixture's `[2]` names a chunk, not a slot; if a
method drops that chunk the marker resolves to nothing, which is count 1 arriving from
*selection* rather than from the model. That coupling is the only reason the second table
says anything the first does not.

Nothing in the module computes a preference. The comparison is reported; the architect
rules.

---

## D-052 — The 0.10 sweep was not hiding a viable floor

**Status:** Measured (PROVISIONAL) · **Phase:** 2D.1f

Re-swept at 0.05 between 0.30 and 0.60 on the local embedder, as instructed, to check
whether the coarse grid's jump from "admits two hard negatives" at 0.35 to "refuses two
covered questions" at 0.45 was a resolution artefact.

It was not. 0.40 still admits one false coverage; 0.45 is the first safe point and the
lowest safe point, unchanged. 0.50 costs nothing extra over 0.45 (identical counts), so
there is slack above the chosen value but none below it.

Recorded because a negative result that is not written down gets re-investigated. The
finer grid is now part of the standing harness rather than a one-off check.
