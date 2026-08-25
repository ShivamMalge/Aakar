"""Item 5 — the budget guard must actually refuse, before anything is spent.

D8: `AAKAR_MAX_USD_PER_RUN`, print projected cost before any live batch, refuse if over.
A guard that has never refused is untested, so these drive it to the refusal.

**Read the last test in this file before trusting the others.** `CostLedger` is not
wired into `CassetteProvider`: nothing calls `preflight` on its own. These tests prove
the guard refuses *when a call site invokes it*, which is not the same as proving every
call path does. That gap is real and is called out explicitly rather than papered over.
"""

from __future__ import annotations

import inspect
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
from aakar.providers import cassette as cassette_module
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


def test_the_guard_is_not_wired_into_the_provider() -> None:
    """States the gap, so it cannot be mistaken for coverage.

    The tests above prove `preflight` refuses when a call site calls it. Nothing in
    `CassetteProvider` calls it, so there is no call path today on which the budget is
    enforced automatically — every future caller has to remember. This test documents
    that and will fail the moment the wiring lands, at which point it should be replaced
    by one asserting the provider itself refuses.

    Phase 2 is the first phase permitted to spend money (spec §7), so this is the phase
    boundary at which the gap stops being theoretical.
    """
    source = inspect.getsource(cassette_module)
    assert "CostLedger" not in source and "preflight" not in source, (
        "CassetteProvider now references the ledger — the budget may be enforced "
        "automatically. Replace this test with one that asserts the provider refuses."
    )
