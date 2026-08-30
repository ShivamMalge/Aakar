"""Phase 2B items 8–12: tiering, the semantic cache, quotas, degraded mode, the ceiling.

Every guard here is driven to its refusal at least once (agents.md R2), and each refusal is
paired with the inverse, because a guard that refuses everything passes a refusal test just
as well as a correct one.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aakar.auth import ensure_owner
from aakar.providers import Cassette, CassetteProvider, ChatRequest, CostLedger, StubProvider
from aakar.rag import (
    DEFAULT_THRESHOLD,
    DegradedReason,
    OwnerQuota,
    QuotaExceeded,
    RegistrationPolicy,
    Tier,
    TierConfig,
    account_count,
    assess,
    check_owner_quota,
    cosine,
    has_capacity,
    lookup,
    questions_today,
    register_or_waitlist,
    scope_key,
    store,
)

CHAT = ChatRequest(model="m", system="s", prompt="what is the lens?")


# ------------------------------------------------------------------ 2B.8 tiering


def test_the_two_tiers_resolve_to_configured_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AAKAR_MODEL", "frontier-model")
    monkeypatch.setenv("AAKAR_ANSWER_MODEL", "small-model")
    config = TierConfig.from_env()
    assert config.model_for(Tier.GENERATION) == "frontier-model"
    assert config.model_for(Tier.ANSWER) == "small-model"


def test_the_answer_tier_falls_back_to_the_generation_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silent downgrade of answer quality is worse than an obvious bill."""
    monkeypatch.setenv("AAKAR_MODEL", "frontier-model")
    monkeypatch.delenv("AAKAR_ANSWER_MODEL", raising=False)
    assert TierConfig.from_env().model_for(Tier.ANSWER) == "frontier-model"


def test_the_ledger_splits_spend_by_tier(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """2B.8's whole purpose: a bill that cannot be split cannot say whether it rose
    because there are more topics or more readers."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=10.0)
    cassette = Cassette(tmp_path)

    CassetteProvider(
        StubProvider(usd_per_call=0.05), cassette, "record", ledger, tier=Tier.GENERATION
    ).chat(CHAT)
    for i in range(3):
        CassetteProvider(
            StubProvider(usd_per_call=0.001), cassette, "record", ledger, tier=Tier.ANSWER
        ).chat(ChatRequest(model="m", system="s", prompt=f"question {i}"))

    split = ledger.by_tier()
    assert split["generation"] == pytest.approx(0.05)
    assert split["answer"] == pytest.approx(0.003)


def test_the_tier_is_recorded_even_when_both_use_one_model(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """The tier is a call-site fact, not something inferred from the model name."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=10.0)
    cassette = Cassette(tmp_path)
    for tier in (Tier.GENERATION, Tier.ANSWER):
        CassetteProvider(
            StubProvider(usd_per_call=0.01), cassette, "record", ledger, tier=tier
        ).chat(ChatRequest(model="same-model", system="s", prompt=str(tier)))

    assert set(ledger.by_tier()) == {"generation", "answer"}


# --------------------------------------------------------------- 2B.9 the cache


def test_cosine_is_sane() -> None:
    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert cosine([0, 0, 0], [1, 0, 0]) == 0.0  # no division by zero


def test_parts_sharing_an_instance_of_share_one_cache_scope() -> None:
    """D-022: two mitochondria are one retrieval target, so one cache scope."""
    assert scope_key("mitochondrion_1", "Mitochondrion") == scope_key(
        "mitochondrion_2", "Mitochondrion"
    )
    # A part with no instance_of keeps its own scope.
    assert scope_key("nucleus", None) != scope_key("nucleolus", None)


def _seed_cache(conn: sqlite3.Connection, owner_id: str, corpus: str, scope: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO corpora (id, content_hash, name) VALUES (?, ?, 'x')",
        (corpus, f"{corpus}h"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES (?, ?, ?, 'eye', 'Eye')",
        (f"t1_{corpus}", owner_id, corpus),
    )
    conn.commit()
    store(
        conn,
        owner_id=owner_id,
        corpus_id=corpus,
        topic_id=f"t1_{corpus}",
        scope=scope,
        question="what does the lens do?",
        question_vector=[1.0, 0.0, 0.0],
        answer={"text": "It focuses light [p. 12]."},
    )


def test_a_close_question_hits(conn: sqlite3.Connection, owner_id: str) -> None:
    _seed_cache(conn, owner_id, "c1", "lens")
    hit = lookup(conn, corpus_id="c1", scope="lens", question_vector=[0.99, 0.14, 0.0])
    assert hit is not None
    assert hit.similarity >= DEFAULT_THRESHOLD
    assert hit.is_paraphrase, "a non-verbatim match must be labelled as similar (D4)"


def test_a_distant_question_misses(conn: sqlite3.Connection, owner_id: str) -> None:
    """Guards the guard: a cache that hits on everything passes the test above."""
    _seed_cache(conn, owner_id, "c1", "lens")
    assert lookup(conn, corpus_id="c1", scope="lens", question_vector=[0.0, 1.0, 0.0]) is None


def test_the_same_question_in_another_corpus_never_hits(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """D-007. The failure this prevents is serving one student's chapter text to another."""
    _seed_cache(conn, owner_id, "c1", "lens")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c2', 'c2h', 'other')")
    conn.commit()

    assert lookup(conn, corpus_id="c1", scope="lens", question_vector=[1.0, 0.0, 0.0]) is not None
    assert lookup(conn, corpus_id="c2", scope="lens", question_vector=[1.0, 0.0, 0.0]) is None


def test_the_same_question_in_another_scope_never_hits(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    _seed_cache(conn, owner_id, "c1", "lens")
    assert lookup(conn, corpus_id="c1", scope="retina", question_vector=[1.0, 0.0, 0.0]) is None


def test_two_owners_on_one_corpus_share_cached_answers(conn: sqlite3.Connection) -> None:
    """The economic claim, made concrete: the second reader pays nothing."""
    alice = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    bob = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    _seed_cache(conn, alice, "shared", "lens")
    conn.execute(
        "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES ('g1', 'shared', ?)", (bob,)
    )
    conn.commit()

    # Bob asks a paraphrase of a question Alice already asked, against the same corpus.
    hit = lookup(conn, corpus_id="shared", scope="lens", question_vector=[0.99, 0.14, 0.0])
    assert hit is not None, "the cache is keyed on the corpus, not on who asked"


# ---------------------------------------------------------------- 2B.10 quota


def _answer_calls(conn: sqlite3.Connection, owner_id: str, n: int, *, cache_hit: int = 0) -> None:
    ledger = CostLedger(conn, owner_id, max_usd_per_run=1000.0)
    from aakar.providers import Usage

    for i in range(n):
        ledger.record(
            kind="chat",
            model="m",
            mode="live",
            usage=Usage(usd=0.001),
            request_hash=f"h{i}",
            cache_hit=bool(cache_hit),
            tier=Tier.ANSWER,
        )


def test_the_owner_quota_refuses_at_the_limit(conn: sqlite3.Connection, owner_id: str) -> None:
    quota = OwnerQuota(max_questions_per_day=3)
    _answer_calls(conn, owner_id, 3)
    with pytest.raises(QuotaExceeded) as raised:
        check_owner_quota(conn, owner_id, quota)
    assert "3" in raised.value.message
    assert raised.value.remedy


def test_under_the_limit_is_allowed(conn: sqlite3.Connection, owner_id: str) -> None:
    quota = OwnerQuota(max_questions_per_day=3)
    _answer_calls(conn, owner_id, 2)
    check_owner_quota(conn, owner_id, quota)


def test_a_cache_hit_is_not_charged_against_the_quota(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """Charging for a free answer would penalise the behaviour the cache encourages."""
    _answer_calls(conn, owner_id, 10, cache_hit=1)
    assert questions_today(conn, owner_id) == 0
    check_owner_quota(conn, owner_id, OwnerQuota(max_questions_per_day=1))


def test_generation_calls_do_not_consume_a_students_question_quota(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    from aakar.providers import Usage

    ledger = CostLedger(conn, owner_id, max_usd_per_run=1000.0)
    for i in range(5):
        ledger.record(
            kind="chat",
            model="m",
            mode="live",
            usage=Usage(usd=0.05),
            request_hash=f"g{i}",
            cache_hit=False,
            tier=Tier.GENERATION,
        )
    assert questions_today(conn, owner_id) == 0


def test_one_owners_quota_does_not_bind_another(conn: sqlite3.Connection) -> None:
    """The gate item: a second owner is unaffected while the first is refused."""
    a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    quota = OwnerQuota(max_questions_per_day=2)

    _answer_calls(conn, a, 2)
    with pytest.raises(QuotaExceeded):
        check_owner_quota(conn, a, quota)
    check_owner_quota(conn, b, quota)


def test_yesterdays_questions_do_not_count(conn: sqlite3.Connection, owner_id: str) -> None:
    _answer_calls(conn, owner_id, 5)
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert questions_today(conn, owner_id, now=tomorrow) == 0


# ------------------------------------------------------------- 2B.11 degraded


def test_a_healthy_system_has_no_banner(conn: sqlite3.Connection) -> None:
    state = assess(conn)
    assert state.healthy and state.banner() is None
    assert state.can_upload and state.can_generate and state.can_serve_cached


def test_budget_exhaustion_stops_generation_but_not_the_library(
    conn: sqlite3.Connection,
) -> None:
    state = assess(conn, budget_exhausted=True)
    assert not state.can_generate
    assert state.can_serve_cached, "cached answers cost nothing; nothing takes them away"
    assert state.can_upload, "uploads do not call a model"
    assert "usage limit" in (state.banner() or "")


def test_a_stalled_worker_stops_uploads_but_not_questions(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """D-035's ruling made concrete: merging this with budget exhaustion would tell a
    student their questions were unavailable when they were not."""
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('d1', ?, 'c1', 'f.pdf', 'h1', '/x')",
        (owner_id,),
    )
    stale = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO ingest_jobs (id, document_id, owner_id, status, pages_total, started_at)"
        " VALUES ('j1', 'd1', ?, 'running', 10, ?)",
        (owner_id, stale),
    )
    conn.commit()

    state = assess(conn)
    assert DegradedReason.WORKER_UNAVAILABLE in state.reasons
    assert not state.can_upload
    assert state.can_generate, "answering a question needs no worker"
    assert state.can_serve_cached
    assert "uploads are paused" in (state.banner() or "")


def test_a_recently_started_job_is_not_a_stalled_worker(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """Guards the guard: a slow document must not be reported as a dead worker."""
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('d1', ?, 'c1', 'f.pdf', 'h1', '/x')",
        (owner_id,),
    )
    recent = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO ingest_jobs (id, document_id, owner_id, status, pages_total, started_at)"
        " VALUES ('j1', 'd1', ?, 'running', 10, ?)",
        (owner_id, recent),
    )
    conn.commit()
    assert assess(conn).healthy


def test_the_causes_are_distinguished_not_merged(conn: sqlite3.Connection) -> None:
    budget = assess(conn, budget_exhausted=True)
    provider = assess(conn, provider_available=False)
    assert budget.reasons != provider.reasons
    assert budget.banner() != provider.banner()


# -------------------------------------------------------- 2B.12 registration


def test_registration_is_allowed_below_the_ceiling(conn: sqlite3.Connection) -> None:
    assert has_capacity(conn, RegistrationPolicy(max_accounts=5))
    admitted, position = register_or_waitlist(conn, "new@example.com", RegistrationPolicy(5))
    assert admitted and position is None


def test_beyond_the_ceiling_a_signup_is_waitlisted_not_refused(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """A refusal loses the person; a waitlist costs one row."""
    policy = RegistrationPolicy(max_accounts=1)
    assert account_count(conn) == 1
    assert not has_capacity(conn, policy)

    admitted, position = register_or_waitlist(conn, "second@example.com", policy)
    assert not admitted
    assert position == 1

    admitted, position = register_or_waitlist(conn, "third@example.com", policy)
    assert position == 2, "positions must be stable and ordered, or they mean nothing"


def test_re_registering_returns_the_same_position(conn: sqlite3.Connection, owner_id: str) -> None:
    policy = RegistrationPolicy(max_accounts=1)
    _, first = register_or_waitlist(conn, "again@example.com", policy)
    _, second = register_or_waitlist(conn, "again@example.com", policy)
    assert first == second
    assert conn.execute("SELECT COUNT(*) AS n FROM waitlist").fetchone()["n"] == 1


def test_the_default_ceiling_is_low(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default low, deliberately far below the 500 the ingest bounds were reasoned against."""
    monkeypatch.delenv("AAKAR_MAX_ACCOUNTS", raising=False)
    assert RegistrationPolicy.from_env().max_accounts <= 50


# ------------------------------------------------- 2B.9 threshold calibration


def test_a_permissive_threshold_is_reported_unsafe_not_just_lower_quality(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """G-03's whole point, as an assertion.

    Hit rate alone is trivially maximised by lowering the threshold, at which point the
    cache answers questions the student did not ask. The harness must call that UNSAFE
    rather than merely reporting a higher number.
    """
    from aakar.rag import QuestionPair, evaluate, recommend

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES ('t1', ?, 'c1', 'eye', 'Eye')",
        (owner_id,),
    )
    conn.commit()

    # Orthogonal-ish vectors: the paraphrase is close, the near-miss is not.
    vectors = {
        "seed": [1.0, 0.0, 0.0],
        "paraphrase": [0.98, 0.2, 0.0],
        "near_miss": [0.75, 0.66, 0.0],
    }

    def embed(text: str) -> list[float]:
        return vectors[text]

    results = evaluate(
        conn,
        owner_id=owner_id,
        corpus_id="c1",
        topic_id="t1",
        scope="lens",
        embed=embed,
        paraphrases=[QuestionPair("seed", "paraphrase", True)],
        near_misses=[QuestionPair("seed", "near_miss", False)],
        thresholds=(0.5, 0.95),
    )

    permissive, strict = results
    assert permissive.hit_rate == 1.0, "a low threshold does buy hit rate"
    assert permissive.false_hits == 1
    assert not permissive.acceptable, "but it must be reported unsafe, not just cheaper"

    assert strict.acceptable and strict.false_hits == 0
    assert recommend(results) is strict, "the recommendation must never be the unsafe one"


def test_one_false_hit_disqualifies_a_threshold_outright() -> None:
    """Absolute, not a rate. One wrong answer served confidently is the failure; there is
    no hit rate that buys it back."""
    from aakar.rag import ThresholdResult

    assert ThresholdResult(threshold=0.9, hits=99, misses=0, false_hits=0).acceptable
    assert not ThresholdResult(threshold=0.9, hits=99, misses=0, false_hits=1).acceptable
