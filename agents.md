# agents.md

Project-wide rules for anyone — human or agent — working in this repository. These are
distinct from `aakar-claude-code-prompt.md` (the brief) and `phases.md` (the roadmap):
they are standing engineering rules, and they apply in every phase.

---

## R1 — A parameter with a default must be able to say "unspecified"

**Any harness, test fixture, or capture request that supplies a parameter with a default
MUST be able to express "unspecified", and at least one test or capture must exercise the
unspecified path.**

Pinning every parameter explicitly means the default is never executed. The code path is
untested while appearing covered, and coverage tooling cannot see the gap because the line
that computes the default is never reached from the harness at all.

### Why this is a standing rule

It has caused three separate defects in this project, each found only by accident:

1. **The Phase 1 route outage.** `readOptions` fell back to a value off a `"use client"`
   module, which React cannot serialize. The fault fired *only when an option was absent* —
   and the screenshot harness supplied `cutaway` and `labels` on every URL. So the harness
   returned 200 while `/render/{topic}`, the URL readers actually open, returned 500. The
   evidence looked healthy for as long as the bug existed.

2. **`camera_hint` distance.** Every golden spec is about one unit across, so an authored
   camera distance looked correct until the first 6-unit topic, which it cropped at both
   ends. The derived-distance path did not exist because nothing had ever needed it.

3. **`ShotRequest.cutaway`.** Pinned to `0` on every capture URL, so the geometry-derived
   cutaway default could never fire in a capture. Every gate image silently showed the
   non-default path.

The shape is always the same: **the default is the untested path, and the harness is what
prevents it from ever running.**

### What compliance looks like

- Tri-state the parameter (`None` / `undefined` means "do not say"), rather than defaulting
  it at the boundary.
- Do not resolve a default in the layer that *reads* input. Resolve it in the layer that
  *uses* it, so the reading layer can pass the absence through.
- Have at least one capture or test that omits it, and assert on what the default produced.

---

## R2 — A guard that has never refused anything is untested

Drive every guard to its refusal at least once, and assert on what it refused. A budget
cap, a quota, a validation error and a precondition are all in this class. Prove the
refusal blocks the thing it guards — a spy that counts invocations beats an exception type,
because an exception says nothing about whether work already happened before it was raised.

Pair it with the inverse: a guard that refuses everything passes a refusal test just as
well as a correct one.

---

## R3 — Verdict agreement is not behavioural agreement

Two implementations that accept and reject the same inputs can still return different
values. When something is generated for two stacks from one source, test both the verdict
and the output, and derive the expected output from the source rather than from either
implementation. D-015 and D-018 were both this shape.

---

## R4 — Report what was not done

A gate report states what was skipped, what was assumed, and what could not be measured,
in the same place as the results. A limitation discovered by the reader in the next phase
costs more than one stated plainly in this one.
