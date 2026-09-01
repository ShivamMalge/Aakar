"""2D.2b/c — exercise the budget guard against a live provider, then record cassettes.

``python -m aakar.evals.record`` and nothing else in the project makes a live call.

## The order is the point

1. **Trip the guard before spending anything.** The cap is set below the preflight estimate,
   a real provider is wired in, and the run must stop with `BudgetExceeded` having made
   zero requests. A guard only ever tested against a stub has been tested against a thing
   that cannot cost money (R2).
2. **Trip it again on accumulated real spend.** The first check only proves the flat
   estimate blocks a first call. This one lets real calls through, accumulates their real
   cost, and stops mid-run — which is the failure the ledger exists for.
3. **Raise the cap and record**, embedding every text the 2D.1 harnesses need, plus one
   answer-tier generation so a human can read one end-to-end answer.

## The key never reaches disk

Cassettes store only the response payload (`vectors`/`text` plus `usage`), keyed by a hash
of the request's *content* fields. There is no header, no client config and no credential
in either the key or the body — see `providers/cassette.py`. This module additionally
refuses to write anything if the key string appears in a payload, which is belt-and-braces
against a provider that one day echoes a request back.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from aakar.auth import ensure_owner
from aakar.db import apply_schema, connect, migrate
from aakar.providers import (
    BudgetExceeded,
    Cassette,
    CassetteProvider,
    CostLedger,
    EmbedRequest,
    GeminiProvider,
)
from aakar.rag.answer import build_prompt
from aakar.rag.embedding import TASK_DOCUMENT, TASK_QUERY, EmbeddingConfig, l2_normalize
from aakar.rag.retrieval import part_scope_terms
from aakar.rag.tiers import Tier

from .golden import GOLDEN_DIR, GoldenSet, load_answers, load_golden_set, rank

#: Cap for step 1. Below `CassetteProvider`'s flat preflight estimate, so the guard must
#: refuse before a request leaves the machine.
TIGHT_CAP_USD = 0.04

#: Cap and estimate for step 2. The estimate is realistic rather than flat, so real calls
#: succeed and the ledger's accumulated spend is what eventually trips the cap.
REAL_ESTIMATE_USD = 0.000002
ACCUMULATION_CAP_USD = 0.000005

#: Retrieval embeddings and the answer generation are both answer-tier work (2B.8). The
#: `llm_calls.tier` CHECK is a closed vocabulary and refused an invented "eval" value — the
#: right behaviour, and the reason this constant is named rather than inlined.
RECORDING_TIER = Tier.ANSWER

#: Step 3. Generous enough to finish; the whole recording is a few thousand tokens.
RECORDING_CAP_USD = 0.50


def load_env(root: Path) -> dict[str, str]:
    """Read `.env` into the process environment.

    **Nothing in the application does this.** `.env.example` says "copy to .env and fill",
    and `Settings.from_env` reads `os.environ`, so a key placed in `.env` is invisible to
    the app itself. That gap is real and is reported rather than papered over; this loader
    exists so the recording harness can run, not to fix it.
    """
    values: dict[str, str] = {}
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw = line.split("=", 1)
        values[name.strip()] = raw.split("  #")[0].strip().strip('"').strip("'")
    os.environ.update(values)
    return values


@dataclass
class Recording:
    embedded_texts: int = 0
    live_calls: int = 0
    usd: float = 0.0


def _ledger(conn: sqlite3.Connection, owner_id: str, cap: float) -> CostLedger:
    return CostLedger(conn, owner_id, cap)


def _provider(cassette: Cassette, ledger: CostLedger, estimate: float) -> CassetteProvider:
    return CassetteProvider(
        GeminiProvider(),
        cassette,
        "record",
        ledger,
        estimate_usd=estimate,
        tier=RECORDING_TIER.value,
    )


def texts_to_record(golden: GoldenSet) -> tuple[list[str], list[str]]:
    """Every text the 2D.1 harnesses embed, split by task type.

    Documents and queries are embedded asymmetrically by the provider, so they are recorded
    under different task types — a cassette recorded with the wrong one would replay
    plausibly and score differently from production.
    """
    documents = [chunk.text for chunk in golden.chunks]

    queries: list[str] = []
    for question in golden.questions:
        terms = part_scope_terms(question.part, question.aliases)
        queries.append(f"{' '.join(terms)} {question.question}")

    pairs = json.loads((GOLDEN_DIR / "cache-pairs.json").read_text(encoding="utf-8"))
    for group in ("paraphrases", "near_misses"):
        for pair in pairs[group]:
            queries.extend([pair["seeded"], pair["probe"]])

    # Deduplicated: the same seeded question appears in several pairs, and paying twice for
    # an identical request would also write the same cassette twice.
    return documents, list(dict.fromkeys(queries))


def step1_guard_refuses_before_spending(
    conn: sqlite3.Connection, owner: str, cassette: Cassette, out: TextIO
) -> bool:
    print("STEP 1 - budget guard, live provider, cap below the preflight estimate", file=out)
    ledger = _ledger(conn, owner, TIGHT_CAP_USD)
    provider = CassetteProvider(
        GeminiProvider(), cassette, "record", ledger, tier=RECORDING_TIER.value
    )
    try:
        provider.embed(
            EmbedRequest(
                model=EmbeddingConfig.from_env().model,
                texts=("this request must never leave the machine",),
                output_dimensionality=768,
                task_type=TASK_QUERY,
            )
        )
    except BudgetExceeded as exc:
        print(f"  REFUSED as required: {exc}", file=out)
        print(f"  ledger spent: ${ledger.spent:.6f} over cap ${TIGHT_CAP_USD:.2f}", file=out)
        rows = conn.execute("SELECT COUNT(*) c FROM llm_calls").fetchone()["c"]
        print(f"  rows in llm_calls: {rows} (zero proves nothing was called)", file=out)
        return True
    print("  GUARD DID NOT FIRE - a live call was made under a cap that should have", file=out)
    print("  refused it. Stopping rather than recording anything else.", file=out)
    return False


def step2_guard_stops_on_accumulated_spend(
    conn: sqlite3.Connection, owner: str, cassette: Cassette, queries: Sequence[str], out: TextIO
) -> bool:
    print(file=out)
    print("STEP 2 - budget guard on ACCUMULATED real spend, mid-run", file=out)
    print(
        f"  cap ${ACCUMULATION_CAP_USD:.6f}, per-call estimate ${REAL_ESTIMATE_USD:.6f}", file=out
    )
    ledger = _ledger(conn, owner, ACCUMULATION_CAP_USD)
    provider = _provider(cassette, ledger, REAL_ESTIMATE_USD)
    config = EmbeddingConfig.from_env()

    made = 0
    for text in queries:
        try:
            provider.embed(
                EmbedRequest(
                    model=config.model,
                    texts=(text,),
                    output_dimensionality=config.dimensions,
                    task_type=TASK_QUERY,
                )
            )
        except BudgetExceeded as exc:
            print(f"  {made} live call(s) succeeded, then: {exc}", file=out)
            print(f"  ledger spent: ${ledger.spent:.8f}", file=out)
            return made > 0
        made += 1
    print(f"  guard never fired after {made} calls (spent ${ledger.spent:.8f})", file=out)
    return False


def step3_record(
    conn: sqlite3.Connection,
    owner: str,
    cassette: Cassette,
    documents: Sequence[str],
    queries: Sequence[str],
    golden: GoldenSet,
    out: TextIO,
) -> Recording:
    print(file=out)
    print("STEP 3 - recording", file=out)
    ledger = _ledger(conn, owner, RECORDING_CAP_USD)
    provider = _provider(cassette, ledger, REAL_ESTIMATE_USD)
    config = EmbeddingConfig.from_env()
    recording = Recording()

    for task, texts in ((TASK_DOCUMENT, documents), (TASK_QUERY, queries)):
        for text in texts:
            provider.embed(
                EmbedRequest(
                    model=config.model,
                    texts=(text,),
                    output_dimensionality=config.dimensions,
                    task_type=task,
                )
            )
            recording.embedded_texts += 1
            if not provider.last_was_cache_hit:
                recording.live_calls += 1
    print(f"  embedded {recording.embedded_texts} texts ({recording.live_calls} live)", file=out)

    # One real answer, so the gate has an end-to-end result a human can read and check
    # against the chapter rather than against another machine's opinion.
    answer_text = _record_one_answer(provider, golden, out)
    recording.usd = ledger.total_usd()
    print(f"  ledger total: ${recording.usd:.6f} (paid-tier list price; see PRICING)", file=out)
    print(f"  by tier: {ledger.by_tier()}", file=out)
    (GOLDEN_DIR / "recorded-answer.txt").write_text(answer_text, encoding="utf-8")
    return recording


def _record_one_answer(provider: CassetteProvider, golden: GoldenSet, out: TextIO) -> str:
    """Generate one answer through the real answer tier and print it for hand-checking."""
    from aakar.providers import ChatRequest  # noqa: PLC0415 - keeps the import surface small

    fixture = next(f for f in load_answers() if f.id == "a08")  # the OCR-citing question
    question = next(q for q in golden.questions if q.id == fixture.question_id)
    embed_config = EmbeddingConfig.from_env()

    # Retrieve for real: the answer must be grounded in what retrieval actually returns,
    # not in the passages the fixture happens to name.
    vectors = [
        provider.embed(
            EmbedRequest(
                model=embed_config.model,
                texts=(chunk.text,),
                output_dimensionality=embed_config.dimensions,
                task_type=TASK_DOCUMENT,
            )
        ).vectors[0]
        for chunk in golden.chunks
    ]
    terms = part_scope_terms(question.part, question.aliases)
    scoped = f"{' '.join(terms)} {question.question}"
    query = provider.embed(
        EmbedRequest(
            model=embed_config.model,
            texts=(scoped,),
            output_dimensionality=embed_config.dimensions,
            task_type=TASK_QUERY,
        )
    ).vectors[0]
    # L2-normalised before ranking. `rank` computes a dot product and calls it cosine,
    # which is only true for unit vectors — and `gemini-embedding-001` does not normalise
    # below 3072 dimensions (D-043). Reading the provider's raw vectors here printed
    # scores around 0.26 that looked like weak retrieval and were simply the wrong number.
    hits = rank(l2_normalize(query), golden.chunks, [l2_normalize(v) for v in vectors])[:5]

    prompt = build_prompt(question.question, hits)
    response = provider.chat(
        ChatRequest(
            model=os.environ.get("AAKAR_ANSWER_MODEL") or os.environ["AAKAR_MODEL"],
            system=prompt.system,
            prompt=prompt.user,
        )
    )

    lines = [
        "2D.2 - one recorded answer, for hand-verification",
        "=" * 49,
        f"question: {question.question}",
        f"part    : {question.part}",
        "",
        "passages given to the model (in marker order):",
    ]
    for index, hit in sorted(prompt.numbering.items()):
        lines.append(
            f"  [{index}] {hit.chunk_id} (p. {hit.page_label}, {hit.source}) score={hit.score:.4f}"
        )
        lines.append(f"       {hit.text}")
    lines += [
        "",
        "answer:",
        response.text,
        "",
        f"tokens: {response.usage.prompt_tokens} in / "
        f"{response.usage.completion_tokens} out  cost: ${response.usage.usd:.6f}",
    ]
    rendered = "\n".join(lines)
    print(file=out)
    print(rendered, file=out)
    return rendered


def main(out: TextIO = sys.stdout) -> int:
    root = Path(__file__).resolve().parents[4]
    load_env(root)
    if os.environ.get("AAKAR_PROVIDER_MODE") == "replay":
        # The .env ships `replay`, which is right for every other entry point.
        os.environ["AAKAR_PROVIDER_MODE"] = "record"

    golden = load_golden_set()
    documents, queries = texts_to_record(golden)
    cassette = Cassette(
        Path(os.environ.get("AAKAR_CASSETTE_DIR", root / "services/api/tests/cassettes"))
    )

    # In-memory: the ledger is the artefact here, not the database. Nothing about this
    # run belongs in the real one.
    conn = connect(Path(":memory:"))
    migrate(conn)
    apply_schema(conn)
    owner = ensure_owner(conn, "record@local", "recording-only-password-long-enough")

    print(
        f"recording against {os.environ['AAKAR_MODEL']} / {os.environ['AAKAR_EMBED_MODEL']}",
        file=out,
    )
    print(f"  {len(documents)} documents, {len(queries)} unique queries", file=out)
    print(file=out)

    if not step1_guard_refuses_before_spending(conn, owner, cassette, out):
        return 1
    step2_guard_stops_on_accumulated_spend(conn, owner, cassette, queries, out)
    step3_record(conn, owner, cassette, documents, queries, golden, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
