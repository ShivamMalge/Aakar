"""3A gate: extraction against the verified label set. ``python -m aakar.evals.structures_eval``

Reports, in this order:

1. **What every number is certified against** — model, chapter commit, label-set commit
   (derived from git, never typed), who verified the labels and when, and the two scope
   limits. Printed on every run, because a caveat that has to be looked up is a caveat that
   will not be.
2. **Precision and recall, twice, as counts** — over all named entities, and over
   `modellable: true` only (architect ruling, D-065). The second is the product-relevant
   number; the first says what the extractor misses. Unmatched entities are listed by name
   on both sides so a near-miss is visible rather than silently counted.
3. **Alias coverage, per entity** — for each labelled entity, do the emitted aliases cover
   every surface form the chapter actually uses (D-046)? Uncovered forms are listed.
4. **The model's chunk-claim accuracy** — confirmed / invented / missed, as a diagnostic.
5. **Cost per chapter**, measured, at paid-tier list price.

Runs in replay against the recorded cassette by default. With `AAKAR_PROVIDER_MODE=record`
and a key in `.env` it makes the one live call under a hard budget cap.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from aakar.auth import ensure_owner
from aakar.config import REPO_ROOT, load_env_file
from aakar.db import apply_schema, connect, migrate
from aakar.providers import Cassette, CassetteProvider, CostLedger, GeminiProvider, Provider
from aakar.rag.tiers import Tier
from aakar.structures import StructureLabels, inflections, load_labels, normalise
from aakar.structures.coverage import baseline, dumps
from aakar.structures.extract import CollisionError, ExtractedEntity, Extraction, extract
from aakar.structures.labels import LabelledEntity

from .golden import GOLDEN_DIR, load_golden_set

TOPIC_SCALE = "the whole human eye, as in specs/golden/human_eye.json"
CAP_USD = 0.10


def _forms(names: tuple[str, ...] | list[str]) -> set[str]:
    out: set[str] = set()
    for n in names:
        out.add(normalise(n))
        out |= {normalise(f) for f in sorted(inflections(n))}
    return out


@dataclass
class Match:
    label: LabelledEntity
    extracted: ExtractedEntity
    via: str


@dataclass
class Scores:
    matches: list[Match] = field(default_factory=list)
    #: Extracted entities matching no label — or matching a label already taken (duplicates).
    false_positives: list[tuple[ExtractedEntity, str]] = field(default_factory=list)
    false_negatives: list[LabelledEntity] = field(default_factory=list)

    def counts(self, *, modellable_only: bool) -> tuple[int, int, int]:
        """(true positives, false positives, false negatives). Counts, never a score."""
        if not modellable_only:
            return len(self.matches), len(self.false_positives), len(self.false_negatives)
        tp = sum(1 for m in self.matches if m.label.modellable)
        fp = sum(1 for e, _ in self.false_positives if e.modellable)
        fn = sum(1 for lab in self.false_negatives if lab.modellable)
        return tp, fp, fn


def score(extraction: Extraction, labels: StructureLabels) -> Scores:
    """Match on intersecting normalised form sets, inflector applied to both sides, so
    humor/humour and RGC/RGCs link. Each label is matched at most once; a second extracted
    entity landing on the same label is a duplicate and counts as a false positive."""
    scores = Scores()
    label_forms = {lab.name: _forms(lab.all_forms) for lab in labels.entities}
    taken: set[str] = set()
    for ent in extraction.entities:
        ent_forms = _forms(ent.all_forms)
        hit = None
        for lab in labels.entities:
            common = ent_forms & label_forms[lab.name]
            if common:
                hit = (lab, sorted(common)[0])
                break
        if hit is None:
            scores.false_positives.append((ent, "no label shares a surface form"))
        elif hit[0].name in taken:
            scores.false_positives.append((ent, f"duplicate of {hit[0].name!r}"))
        else:
            taken.add(hit[0].name)
            scores.matches.append(Match(hit[0], ent, hit[1]))
    scores.false_negatives = [lab for lab in labels.entities if lab.name not in taken]
    return scores


@dataclass(frozen=True)
class AliasCoverage:
    label: str
    covered: tuple[str, ...]
    uncovered: tuple[str, ...]


def alias_coverage(scores: Scores) -> list[AliasCoverage]:
    """D-046, made mechanical: for each matched label, is every surface form the chapter
    actually uses present in the extracted alias set?"""
    out: list[AliasCoverage] = []
    for m in scores.matches:
        have = {normalise(f) for f in m.extracted.all_forms}
        covered = tuple(f for f in m.label.surface_forms if normalise(f) in have)
        uncovered = tuple(f for f in m.label.surface_forms if normalise(f) not in have)
        out.append(AliasCoverage(m.label.name, covered, uncovered))
    return out


def _git_short(path: Path) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "log", "-1", "--format=%h", "--", str(path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=path.parent,
    )
    return out.stdout.strip() or "uncommitted"


def _provider(model: str, cap: float) -> tuple[Provider, CostLedger]:
    mode = os.environ.get("AAKAR_PROVIDER_MODE", "replay")
    conn = connect(Path(":memory:"))
    migrate(conn)
    apply_schema(conn)
    owner = ensure_owner(conn, "structures-eval@local", "eval-only-password-long-enough")
    ledger = CostLedger(conn, owner, cap)
    cassette = Cassette(
        Path(os.environ.get("AAKAR_CASSETTE_DIR") or REPO_ROOT / "services/api/tests/cassettes")
    )
    inner = GeminiProvider() if mode != "replay" else None
    return CassetteProvider(inner, cassette, mode, ledger, tier=Tier.GENERATION.value), ledger


def run(out: TextIO = sys.stdout) -> int:
    load_env_file()
    labels = load_labels()
    golden = load_golden_set()
    model = os.environ.get("AAKAR_MODEL", "gemini-3.6-flash")
    chunks = {c.chunk_id: (c.page_label, c.text) for c in golden.chunks}

    print("3A gate - structure extraction against the verified label set", file=out)
    print("=" * 62, file=out)
    print("certified against", file=out)
    print(f"  model             : {model}", file=out)
    chapter_commit = _git_short(GOLDEN_DIR / "chapter.json")
    print(f"  chapter           : {GOLDEN_DIR.name}/chapter.json @ {chapter_commit}", file=out)
    print(f"  label set         : {labels.path.name} @ {labels.label_set_commit}", file=out)
    print(f"  labels verified by: {labels.verified_by} on {labels.verified_on}", file=out)
    print(f"  measured on       : {dt.date.today().isoformat()}", file=out)
    print(f"  provider mode     : {os.environ.get('AAKAR_PROVIDER_MODE', 'replay')}", file=out)
    for key, note in labels.scope_limits.items():
        if key[:1].isdigit():
            print(f"  scope limit       : {note.split('.')[0]}.", file=out)
    if labels.provisional:
        print("  PROVISIONAL: labels not human-verified", file=out)
    print(file=out)

    provider, ledger = _provider(model, CAP_USD)
    try:
        extraction = extract(
            provider,
            chunks,
            model=model,
            topic_scale=TOPIC_SCALE,
            category_nouns=labels.rules.category_nouns,
        )
    except CollisionError as exc:
        print("EXTRACTION REFUSED - R3 collision (this is the result, not an error):", file=out)
        for c in exc.collisions:
            print(f"  {c.form!r} claimed by {', '.join(c.entities)}", file=out)
        return 2

    record = baseline(extraction, chapter_id="golden-chapter", topic_scale=TOPIC_SCALE)
    (GOLDEN_DIR.parent / "golden-structures" / "extracted.json").write_text(
        dumps(record), encoding="utf-8"
    )

    scores = score(extraction, labels)
    print("extraction", file=out)
    print(f"  proposed by model : {extraction.raw_entity_count}", file=out)
    print(f"  kept              : {len(extraction.entities)}", file=out)
    print(f"  dropped           : {len(extraction.dropped)}", file=out)
    for d in extraction.dropped:
        print(f"    - {d.name!r:<28} {d.rule:<10} {d.detail}", file=out)
    print(f"  synonyms rejected : {len(extraction.rejected_synonyms)}", file=out)
    for n, _synonym, r in extraction.rejected_synonyms:
        print(f"    - {n!r}: {r}", file=out)
    print(f"  unverifiable forms: {len(extraction.unverifiable_forms)}", file=out)
    for n, f in extraction.unverifiable_forms:
        print(f"    - {n!r} claimed {f!r}, not in the chapter", file=out)
    print(file=out)

    print("precision and recall - counts, never a score (D-065: reported twice)", file=out)
    for label, only in (("all named entities", False), ("modellable: true only", True)):
        tp, fp, fn = scores.counts(modellable_only=only)
        print(f"  {label}", file=out)
        print(f"    true positives  : {tp}", file=out)
        print(f"    false positives : {fp}   (precision denominator {tp + fp})", file=out)
        print(f"    false negatives : {fn}   (recall denominator {tp + fn})", file=out)
    print("  unmatched labels (false negatives):", file=out)
    for lab in scores.false_negatives:
        print(
            f"    - {lab.name!r} modellable={lab.modellable} forms={list(lab.surface_forms)}",
            file=out,
        )
    print("  unmatched extractions (false positives):", file=out)
    for ent, why in scores.false_positives:
        print(f"    - {ent.name!r} modellable={ent.modellable}: {why}", file=out)
    print(file=out)

    cov = alias_coverage(scores)
    full = sum(1 for ac in cov if not ac.uncovered)
    print(
        "alias coverage - do the emitted aliases cover the forms the chapter uses (D-046)",
        file=out,
    )
    print(f"  matched entities fully covered : {full} / {len(cov)}", file=out)
    for ac in cov:
        if ac.uncovered:
            print(f"    - {ac.label!r}: uncovered {list(ac.uncovered)}", file=out)
    print(file=out)

    agree = sum(1 for m in scores.matches if m.extracted.modellable == m.label.modellable)
    print("modellable - model's guess vs the verified label, on matched entities", file=out)
    print(f"  agree: {agree} / {len(scores.matches)}", file=out)
    for m in scores.matches:
        if m.extracted.modellable != m.label.modellable:
            print(
                f"    - {m.label.name!r}: model={m.extracted.modellable} "
                f"label={m.label.modellable}",
                file=out,
            )
    print(file=out)

    confirmed = sum(len(e.claims_confirmed) for e in extraction.entities)
    invented = sum(len(e.claims_dropped) for e in extraction.entities)
    missed = sum(len(e.claims_missed) for e in extraction.entities)
    print(
        "model chunk claims - diagnostic; the output uses the matcher's chunks, not these", file=out
    )
    print(f"  confirmed: {confirmed}   invented: {invented}   missed: {missed}", file=out)
    print(file=out)

    u = extraction.usage
    print("cost per chapter - measured, paid-tier list price (PRICING)", file=out)
    print(f"  tokens : {u.prompt_tokens} in / {u.completion_tokens} out", file=out)
    print(f"  usd    : ${u.usd:.6f}   ledger total ${ledger.total_usd():.6f}", file=out)
    print(file=out)

    # The refined guard, on the SAME model response (replayed from the cassette, so it
    # costs nothing and differs only in the deterministic half). Reported beside the
    # approved guard, not in place of it: the architect rules (D-067).
    from aakar.structures.extract import decide, parse_response  # noqa: PLC0415

    replayed = provider.chat(
        __import__("aakar.providers", fromlist=["ChatRequest"]).ChatRequest(
            model=model,
            system=__import__("aakar.structures.extract", fromlist=["SYSTEM"]).SYSTEM,
            prompt=__import__("aakar.structures.extract", fromlist=["build_prompt"]).build_prompt(
                chunks, TOPIC_SCALE
            ),
            max_tokens=8192,
        )
    )
    proposed = parse_response(replayed.text)
    alternatives = (
        (
            "refined synonym guard",
            "own-name token rejected only when it is a category noun",
            {"guard": "refined"},
        ),
        (
            "singular recovery",
            "a plural copied from the text also emits its singular when the chapter contains it",
            {"recover_singulars": True},
        ),
        (
            "both",
            "refined guard + singular recovery",
            {"guard": "refined", "recover_singulars": True},
        ),
    )
    for title, what, kwargs in alternatives:
        print(f"ALTERNATIVE, measured not switched - {title} (D-067)", file=out)
        print(f"  {what}", file=out)
        try:
            alt = decide(proposed, chunks, category_nouns=labels.rules.category_nouns, **kwargs)
        except CollisionError as exc:
            print("  EXTRACTION REFUSED - R3 collision", file=out)
            for c in exc.collisions:
                print(f"    {c.form!r} claimed by {', '.join(c.entities)}", file=out)
            print(file=out)
            continue
        asc = score(alt, labels)
        acov = alias_coverage(asc)
        print(f"  synonyms rejected : {len(alt.rejected_synonyms)}", file=out)
        for n, _synonym, r in alt.rejected_synonyms:
            print(f"    - {n!r}: {r}", file=out)
        tp, fp, fn = asc.counts(modellable_only=False)
        print(f"  all entities      : TP {tp}  FP {fp}  FN {fn}", file=out)
        tp, fp, fn = asc.counts(modellable_only=True)
        print(f"  modellable only   : TP {tp}  FP {fp}  FN {fn}", file=out)
        afull = sum(1 for ac in acov if not ac.uncovered)
        print(f"  alias coverage    : {afull} / {len(acov)} fully covered", file=out)
        for ac in acov:
            if ac.uncovered:
                print(f"    - {ac.label!r}: uncovered {list(ac.uncovered)}", file=out)
        print(file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
