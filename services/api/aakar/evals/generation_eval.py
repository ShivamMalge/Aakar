"""3B gate: spec generation, measured. ``python -m aakar.evals.generation_eval``

For each of the three golden topics:

1. Extract the structure set from the chapter (3A, one call — replayed for the eye).
2. Generate `TRIALS` specs at production temperature, each a distinct recording via a
   trial nonce. **No repair, no retry.** Every generation is classified: JSON? schema-valid
   on the first attempt? referentially valid? Then every citation is re-checked.
3. Compare the first valid generation to the hand-written golden spec — present/absent
   both ways, parent-graph shape, geometry distribution. Not a score.

Then the item the gate says matters most: **do zero-provenance parts actually occur?**
Counted across every generation of every topic, and additionally forced by an ablation on
the eye — the fovea's only naming chunk is withheld from both the passages and the
structure set, and the generator is watched: does it still include the fovea, and if so,
does it carry `[]` (honest) or cite the nearest chunk (fabricated)? If no generation
anywhere emits an empty `chunk_ids`, the runner says STOP, because that is a finding and
not a pass (3B.2).

Every number is certified against the model named, the chapter and golden-spec commits
printed, and the temperature used. Cost per topic is measured at paid-tier list price.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from aakar.auth import ensure_owner
from aakar.config import REPO_ROOT, load_env_file
from aakar.db import apply_schema, connect, migrate
from aakar.generation import (
    SYSTEM,
    GenerationOutcome,
    build_prompt,
    classify,
    compare_to_golden,
    generate,
    verify_provenance,
)
from aakar.providers import Cassette, CassetteProvider, CostLedger, GeminiProvider, Provider
from aakar.rag.tiers import Tier
from aakar.structures import load_labels
from aakar.structures.coverage import baseline
from aakar.structures.extract import CollisionError, extract

TRIALS = 10
ABLATION_TRIALS = 3
TEMPERATURE = 0.0
CAP_USD = 2.00

SCHEMA_PATH = REPO_ROOT / "packages" / "scenespec" / "scenespec.schema.json"
GOLDEN_SPECS = REPO_ROOT / "specs" / "golden"
EVIDENCE = REPO_ROOT / "evidence" / "phase3b"

#: topic -> (chapter file, exemplar topic, title, scale). The exemplar is never the target.
TOPICS: dict[str, tuple[Path, str, str, str]] = {
    "human_eye": (
        REPO_ROOT / "evals" / "golden-provenance" / "chapter.json",
        "animal_cell",
        "The Human Eye",
        "the whole human eye",
    ),
    "animal_cell": (
        REPO_ROOT / "evals" / "golden-generation" / "animal_cell" / "chapter.json",
        "human_eye",
        "The Animal Cell",
        "one whole animal cell and its organelles",
    ),
    "earth_layers": (
        REPO_ROOT / "evals" / "golden-generation" / "earth_layers" / "chapter.json",
        "human_eye",
        "Layers of the Earth",
        "the whole Earth in cross-section",
    ),
}


def _git_short(path: Path) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "log", "-1", "--format=%h", "--", str(path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=path.parent,
    )
    return out.stdout.strip() or "uncommitted"


def _chunks(chapter: Path) -> dict[str, tuple[str, str]]:
    raw = json.loads(chapter.read_text(encoding="utf-8"))
    return {str(c["id"]): (str(c["page_label"]), str(c["text"])) for c in raw["chunks"]}


def _provider(cap: float) -> tuple[Provider, CostLedger]:
    mode = os.environ.get("AAKAR_PROVIDER_MODE", "replay")
    conn = connect(Path(":memory:"))
    migrate(conn)
    apply_schema(conn)
    owner = ensure_owner(conn, "generation-eval@local", "eval-only-password-long-enough")
    ledger = CostLedger(conn, owner, cap)
    cassette = Cassette(
        Path(os.environ.get("AAKAR_CASSETTE_DIR") or REPO_ROOT / "services/api/tests/cassettes")
    )
    inner = GeminiProvider() if mode != "replay" else None
    return CassetteProvider(inner, cassette, mode, ledger, tier=Tier.GENERATION.value), ledger


@dataclass
class TopicResult:
    topic: str
    outcomes: list[GenerationOutcome] = field(default_factory=list)
    usd: float = 0.0

    @property
    def schema_valid(self) -> int:
        return sum(o.schema_valid for o in self.outcomes)

    @property
    def referential_valid(self) -> int:
        return sum(o.referential_valid for o in self.outcomes if o.schema_valid)

    @property
    def valid(self) -> int:
        return sum(o.valid for o in self.outcomes)

    @property
    def zero_provenance_parts(self) -> int:
        return sum(len(o.zero_provenance) for o in self.outcomes)

    @property
    def fabricated(self) -> int:
        return sum(len(o.fabricated) for o in self.outcomes)

    @property
    def first_valid(self) -> GenerationOutcome | None:
        return next((o for o in self.outcomes if o.valid), None)


def run_topic(
    provider: Provider,
    *,
    topic: str,
    model: str,
    schema: dict[str, Any],
    category_nouns: frozenset[str],
    trials: int,
    withhold: set[str] | None = None,
    withhold_structures: set[str] | None = None,
    out: TextIO,
) -> TopicResult:
    chapter, exemplar_topic, title, scale = TOPICS[topic]
    chunks = _chunks(chapter)
    if withhold:
        chunks = {k: v for k, v in chunks.items() if k not in withhold}

    # 3A on this chapter. One call per chapter; the model proposes, the code decides.
    extraction = extract(
        provider, chunks, model=model, topic_scale=scale, category_nouns=category_nouns
    )
    structures = baseline(extraction, chapter_id=topic, topic_scale=scale)["entities"]
    if withhold_structures:
        lowered = {s.lower() for s in withhold_structures}
        structures = [s for s in structures if s["name"].lower() not in lowered]
    print(f"  structures from 3A: {len(structures)} (extraction ${extraction.usd:.6f})", file=out)

    exemplar = json.loads((GOLDEN_SPECS / f"{exemplar_topic}.json").read_text(encoding="utf-8"))
    result = TopicResult(topic=topic, usd=extraction.usd)
    for trial in range(1, trials + 1):
        prompt = build_prompt(
            schema=schema,
            exemplar=exemplar,
            exemplar_note=f"golden spec for {exemplar_topic}",
            topic=topic,
            title=title,
            scale=scale,
            chunks=chunks,
            structures=structures,
            nonce=f"{trial}/{trials}" + ("-ablation" if withhold else ""),
        )
        text, usage = generate(
            provider, model=model, system=SYSTEM, prompt=prompt, temperature=TEMPERATURE
        )
        outcome = verify_provenance(classify(text), chunks)
        outcome.usage = usage
        result.outcomes.append(outcome)
        result.usd += usage.usd
        tag = "ablation-" if withhold else ""
        (EVIDENCE / topic).mkdir(parents=True, exist_ok=True)
        (EVIDENCE / topic / f"{tag}gen-{trial:02d}.json").write_text(
            outcome.raw if outcome.document is None else json.dumps(outcome.document, indent=1),
            encoding="utf-8",
        )
        flag = (
            "valid"
            if outcome.valid
            else ("schema-invalid" if not outcome.schema_valid else "referential-invalid")
        )
        if outcome.document is None:
            flag = f"NOT JSON ({outcome.parse_error})"
        print(
            f"    trial {trial:>2}: {flag:<20} parts={outcome.part_count:<3} "
            f"zero-prov={len(outcome.zero_provenance):<2} fabricated={len(outcome.fabricated):<2} "
            f"unknown-chunk={len(outcome.unknown_chunks):<2} ${usage.usd:.5f}",
            file=out,
        )
        for err in outcome.schema_errors[:3]:
            print(f"             schema: {err}", file=out)
        for err in outcome.referential_errors[:3]:
            print(f"             referential: {err}", file=out)
    return result


def run(out: TextIO = sys.stdout) -> int:
    load_env_file()
    model = os.environ.get("AAKAR_MODEL", "gemini-3.6-flash")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    labels = load_labels()
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    print("3B gate - spec generation, measured", file=out)
    print("=" * 35, file=out)
    print("certified against", file=out)
    print(f"  model        : {model}   temperature {TEMPERATURE}   trials/topic {TRIALS}", file=out)
    print(f"  schema       : {SCHEMA_PATH.name} @ {_git_short(SCHEMA_PATH)}", file=out)
    for topic, (chapter, exemplar, _t, _s) in TOPICS.items():
        print(
            f"  {topic:<12} : chapter @ {_git_short(chapter)}   golden @ "
            f"{_git_short(GOLDEN_SPECS / f'{topic}.json')}   exemplar={exemplar}",
            file=out,
        )
    print(f"  measured on  : {dt.date.today().isoformat()}", file=out)
    print(f"  provider mode: {os.environ.get('AAKAR_PROVIDER_MODE', 'replay')}", file=out)
    for key, note in labels.scope_limits.items():
        if key[:1].isdigit():
            print(f"  scope limit  : {note.split('.')[0]}.", file=out)
    print("  licence      : all three chapters are OpenStax, CC BY-NC-SA 4.0 (D-069)", file=out)
    print(file=out)

    provider, ledger = _provider(CAP_USD)
    results: dict[str, TopicResult] = {}
    for topic in TOPICS:
        print(f"{topic}", file=out)
        try:
            results[topic] = run_topic(
                provider,
                topic=topic,
                model=model,
                schema=schema,
                category_nouns=labels.rules.category_nouns,
                trials=TRIALS,
                out=out,
            )
        except CollisionError as exc:
            print(f"  3A REFUSED ({exc}); topic skipped", file=out)
        print(file=out)

    print("rates - first attempt, no repair, no retry (3B.4)", file=out)
    print(
        f"  {'topic':<12} {'schema-valid':>12} {'referential':>12} {'both':>6} "
        f"{'zero-prov parts':>15} {'fabricated':>10} {'usd':>9}",
        file=out,
    )
    for topic, r in results.items():
        n = len(r.outcomes)
        print(
            f"  {topic:<12} {r.schema_valid:>7}/{n:<4} {r.referential_valid:>7}/{n:<4} "
            f"{r.valid:>3}/{n:<2} {r.zero_provenance_parts:>15} {r.fabricated:>10} "
            f"{r.usd:>9.4f}",
            file=out,
        )
    print(file=out)

    # ------------------------------------------------ the gate item that matters
    total_zero = sum(r.zero_provenance_parts for r in results.values())
    print("zero-provenance parts (3B.2) - must actually occur", file=out)
    print(f"  across all natural generations: {total_zero}", file=out)
    for topic, r in results.items():
        ids = Counter(pid for o in r.outcomes for pid in o.zero_provenance)
        if ids:
            print(f"    {topic}: {dict(ids.most_common(8))}", file=out)
    print(file=out)

    print("ablation - human_eye with c08 (the fovea's only naming chunk) withheld", file=out)
    ablation = run_topic(
        provider,
        topic="human_eye",
        model=model,
        schema=schema,
        category_nouns=labels.rules.category_nouns,
        trials=ABLATION_TRIALS,
        withhold={"c08"},
        withhold_structures={"fovea", "fovea centralis"},
        out=out,
    )
    fovea_seen = fovea_honest = fovea_fabricated = 0
    for o in ablation.outcomes:
        if o.document is None:
            continue
        for part in o.document.get("parts", []):
            name = str(part.get("name", "")).lower()
            aliases = " ".join(str(a) for a in part.get("aliases", []) or []).lower()
            if "fovea" in name or "fovea" in aliases or "macula" in name:
                fovea_seen += 1
                cited = (part.get("provenance") or {}).get("chunk_ids") or []
                if not cited:
                    fovea_honest += 1
                else:
                    fovea_fabricated += 1
    print(
        f"  fovea still included in {fovea_seen} of {ABLATION_TRIALS} generations: "
        f"{fovea_honest} with empty chunk_ids (honest), {fovea_fabricated} citing a chunk "
        f"that cannot name it (fabricated)",
        file=out,
    )
    ablation_zero = ablation.zero_provenance_parts
    print(f"  zero-provenance parts in the ablation: {ablation_zero}", file=out)
    print(file=out)

    if total_zero == 0 and ablation_zero == 0:
        print(
            "STOP: no generation anywhere emitted empty chunk_ids. The generator always", file=out
        )
        print(
            "      finds something to cite. That is the 3B.2 failure, reported as a finding.",
            file=out,
        )
    print(file=out)

    # ------------------------------------------------ against the golden specs
    for topic, r in results.items():
        first = r.first_valid
        print(f"{topic} vs golden (first valid generation)", file=out)
        if first is None or first.document is None:
            print("  no valid generation to compare", file=out)
            print(file=out)
            continue
        golden = json.loads((GOLDEN_SPECS / f"{topic}.json").read_text(encoding="utf-8"))
        cmp = compare_to_golden(first.document, golden)
        print(f"  matched            : {len(cmp.matched)}", file=out)
        print(f"  in golden, not gen : {list(cmp.only_in_golden)}", file=out)
        print(f"  in gen, not golden : {list(cmp.only_in_generated)}", file=out)
        print(f"  golden shape       : {cmp.golden_shape}", file=out)
        print(f"  generated shape    : {cmp.generated_shape}", file=out)
        print(f"  golden geometry    : {cmp.golden_geometry}", file=out)
        print(f"  generated geometry : {cmp.generated_geometry}", file=out)
        print(f"  fabricated cites   : {list(first.fabricated)}", file=out)
        print(f"  zero-provenance    : {list(first.zero_provenance)}", file=out)
        print(file=out)

    print("cost - paid-tier list price, repair budget not in play", file=out)
    for topic, r in results.items():
        per = r.usd / max(1, len(r.outcomes))
        print(
            f"  {topic:<12} ${r.usd:.4f} for {len(r.outcomes)} generations + extraction"
            f" (${per:.4f} per generation)",
            file=out,
        )
    print(f"  ablation     ${ablation.usd:.4f}", file=out)
    print(f"  ledger total ${ledger.total_usd():.4f}", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
