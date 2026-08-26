"""Item 5 — the budget guard must actually refuse, before anything is spent.

D8: `AAKAR_MAX_USD_PER_RUN`, print projected cost before any live batch, refuse if over.
A guard that has never refused is untested, so these drive it to the refusal.

As of 2A.1 the ledger is wired **into** `CassetteProvider`, so the guard is no longer
something a call site must remember to invoke. The preflight sits after the cassette and
before the provider: a replayed or cached call returns above it and costs nothing, so a
cache hit can never be refused for budget, while every call that would actually spend is
checked first.

The tests that call `preflight` directly are kept: they cover the ledger's own arithmetic,
which is a separate thing from where it is invoked from.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aakar.providers import (
    BudgetExceeded,
    Cassette,
    CassetteProvider,
    ChatRequest,
    CostLedger,
    StubProvider,
    Usage,
)
from aakar.providers.base import ChatResponse, EmbedRequest, EmbedResponse, VlmRequest

RECORDED_COST_USD = 0.02
CHAT = ChatRequest(model="m", system="s", prompt="what is the lens?")


class SpyProvider:
    """Counts invocations, so "blocked before any provider invocation" is measurable."""

    def __init__(self, usd: float) -> None:
        self.calls = 0
        self._inner = StubProvider(usd_per_call=usd)

    def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls += 1
        return self._inner.chat(req)

    def vlm(self, req: VlmRequest) -> ChatResponse:
        self.calls += 1
        return self._inner.vlm(req)

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        self.calls += 1
        return self._inner.embed(req)


def test_preflight_blocks_a_call_that_would_exceed_the_budget(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """Budget set below the cost of the call; the provider must never be reached."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=RECORDED_COST_USD / 2)
    spy = SpyProvider(usd=RECORDED_COST_USD)
    provider = CassetteProvider(spy, Cassette(tmp_path), "record")

    with pytest.raises(BudgetExceeded) as raised:
        # The documented call-site contract: cost the call, then make it.
        ledger.preflight(RECORDED_COST_USD)
        provider.chat(CHAT)

    assert spy.calls == 0, "the provider was invoked despite the budget being exceeded"
    assert f"{RECORDED_COST_USD / 2:.2f}" in str(raised.value)
    assert ledger.total_usd() == 0.0, "a refused run still wrote a cost row"


def test_preflight_allows_a_call_inside_the_budget(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """Guards the guard: a budget that refuses everything would pass the test above."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=RECORDED_COST_USD * 10)
    spy = SpyProvider(usd=RECORDED_COST_USD)
    provider = CassetteProvider(spy, Cassette(tmp_path), "record")

    ledger.preflight(RECORDED_COST_USD)
    response = provider.chat(CHAT)

    assert spy.calls == 1
    assert response.usage.usd == pytest.approx(RECORDED_COST_USD)


def test_the_budget_accounts_for_what_has_already_been_spent(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """The cap is per run, not per call: spend must accumulate or it caps nothing."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=0.10)
    for _ in range(4):
        ledger.preflight(0.02)
        ledger.record(
            kind="chat",
            model="m",
            mode="live",
            usage=Usage(usd=0.02),
            request_hash="h",
            cache_hit=False,
        )
    assert ledger.spent == pytest.approx(0.08)

    ledger.preflight(0.02)  # 0.10 exactly — at the cap, not over it
    with pytest.raises(BudgetExceeded):
        ledger.preflight(0.03)


def test_replayed_calls_do_not_consume_the_budget(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """Replay spends nothing, so CI must never be able to trip the cap."""
    cassette = Cassette(tmp_path)
    CassetteProvider(StubProvider(usd_per_call=RECORDED_COST_USD), cassette, "record").chat(CHAT)

    ledger = CostLedger(conn, owner_id, max_usd_per_run=0.001)
    replayed = CassetteProvider(None, cassette, "replay").chat(CHAT)
    ledger.record(
        kind="chat",
        model="m",
        mode="replay",
        usage=replayed.usage,
        request_hash="h",
        cache_hit=True,
    )
    assert ledger.spent == 0.0
    ledger.preflight(0.0)


def test_the_provider_itself_refuses_when_over_budget(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """2A.1: the guard is now inside the only path that can spend money.

    This replaces `test_the_guard_is_not_wired_into_the_provider`, which existed to fail
    the moment this wiring landed. It did.
    """
    ledger = CostLedger(conn, owner_id, max_usd_per_run=0.001)
    spy = SpyProvider(usd=RECORDED_COST_USD)
    provider = CassetteProvider(spy, Cassette(tmp_path), "record", ledger)

    with pytest.raises(BudgetExceeded):
        provider.chat(CHAT)

    assert spy.calls == 0, "the provider was reached despite the budget being exceeded"


def test_a_wired_provider_logs_every_call(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """`llm_calls` is meant to be a truthful record of what happened."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=10.0)
    provider = CassetteProvider(
        SpyProvider(usd=RECORDED_COST_USD), Cassette(tmp_path), "record", ledger
    )
    provider.chat(CHAT)
    provider.embed(EmbedRequest(model="e", texts=("retina",)))

    rows = conn.execute("SELECT kind, mode, cache_hit, usd FROM llm_calls ORDER BY kind").fetchall()
    # The cassette keys on "embed"; the ledger's vocabulary is "embedding" (CHECK
    # constraint on llm_calls.kind), mapped at the boundary.
    assert [r["kind"] for r in rows] == ["chat", "embedding"]
    assert all(r["mode"] == "record" for r in rows)
    assert all(r["cache_hit"] == 0 for r in rows)
    assert ledger.total_usd() == pytest.approx(RECORDED_COST_USD * 2)


def test_a_replayed_call_is_logged_but_free(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """A cache hit that left no trace would make Phase 2B's hit rate unmeasurable."""
    cassette = Cassette(tmp_path)
    CassetteProvider(SpyProvider(usd=RECORDED_COST_USD), cassette, "record").chat(CHAT)

    ledger = CostLedger(conn, owner_id, max_usd_per_run=0.0001)
    replayed = CassetteProvider(None, cassette, "replay", ledger)

    # Under the cap only because a replay spends nothing — the preflight is never
    # reached, since the cassette answers first.
    response = replayed.chat(CHAT)
    assert response.usage.usd == 0.0

    row = conn.execute("SELECT kind, mode, cache_hit, usd FROM llm_calls").fetchone()
    assert (row["kind"], row["mode"], row["cache_hit"], row["usd"]) == ("chat", "replay", 1, 0.0)
    assert ledger.spent == 0.0


def test_a_cache_hit_never_consumes_budget(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """The preflight sits after the cassette, so a hit cannot be refused for cost."""
    cassette = Cassette(tmp_path)
    CassetteProvider(SpyProvider(usd=RECORDED_COST_USD), cassette, "record").chat(CHAT)

    exhausted = CostLedger(conn, owner_id, max_usd_per_run=0.0)
    provider = CassetteProvider(None, cassette, "replay", exhausted)
    assert provider.chat(CHAT).text  # would raise if the guard ran before the cassette


def test_the_estimate_is_charged_before_the_call_not_after(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """The true cost is unknown until the response returns, so the guard charges a
    pessimistic flat estimate up front. An estimate that is too low would re-open the hole
    the guard exists to close."""
    from aakar.providers.cassette import DEFAULT_ESTIMATE_USD

    # Cap sits just under the estimate: the call must be refused even though the stub
    # would in fact have cost far less.
    ledger = CostLedger(conn, owner_id, max_usd_per_run=DEFAULT_ESTIMATE_USD - 0.001)
    spy = SpyProvider(usd=0.000001)
    provider = CassetteProvider(spy, Cassette(tmp_path), "record", ledger)

    with pytest.raises(BudgetExceeded):
        provider.chat(CHAT)
    assert spy.calls == 0
