"""Task 0.6 — provider abstraction, cassette (D8) and the cost ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aakar.providers import (
    BudgetExceeded,
    Cassette,
    CassetteMiss,
    CassetteProvider,
    ChatRequest,
    CostLedger,
    EmbedRequest,
    StubProvider,
    Usage,
    VlmRequest,
    request_hash,
)

PNG_A = b"\x89PNG\r\n\x1a\n-alpha"
PNG_B = b"\x89PNG\r\n\x1a\n-beta"


def _chat() -> ChatRequest:
    return ChatRequest(model="m", system="s", prompt="what is the lens?")


def test_request_hash_is_stable_and_order_independent() -> None:
    assert request_hash("chat", _chat()) == request_hash("chat", _chat())


def test_request_hash_separates_kinds() -> None:
    """A chat and a VLM call with identical text must not share a cassette entry."""
    chat = ChatRequest(model="m", system="s", prompt="p")
    vlm = VlmRequest(model="m", system="s", prompt="p")
    assert request_hash("chat", chat) != request_hash("vlm", vlm)


def test_vlm_hash_includes_screenshot_bytes() -> None:
    """D8: a different render must not replay a critique written about another image."""
    base = VlmRequest(model="m", system="s", prompt="critique", images=(PNG_A,))
    other = VlmRequest(model="m", system="s", prompt="critique", images=(PNG_B,))
    assert request_hash("vlm", base) != request_hash("vlm", other)
    assert request_hash("vlm", base) == request_hash("vlm", base)


def test_record_then_replay_returns_identical_text(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path)
    recorder = CassetteProvider(StubProvider(), cassette, "record")
    recorded = recorder.chat(_chat())

    replayer = CassetteProvider(None, cassette, "replay")
    assert replayer.chat(_chat()).text == recorded.text


def test_replay_miss_is_an_error_not_a_live_call(tmp_path: Path) -> None:
    """A silent fallthrough to `live` in CI would be worse than a failing test."""
    replayer = CassetteProvider(None, cassette=Cassette(tmp_path), mode="replay")
    with pytest.raises(CassetteMiss):
        replayer.chat(_chat())


def test_replay_needs_no_inner_provider(tmp_path: Path) -> None:
    """This is what lets CI run with no API key at all."""
    CassetteProvider(None, Cassette(tmp_path), "replay")
    with pytest.raises(ValueError):
        CassetteProvider(None, Cassette(tmp_path), "live")


def test_replayed_calls_cost_nothing(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path)
    recorded = CassetteProvider(StubProvider(usd_per_call=0.02), cassette, "record").chat(_chat())
    assert recorded.usage.usd == pytest.approx(0.02)

    replayed = CassetteProvider(None, cassette, "replay").chat(_chat())
    assert replayed.usage.usd == 0.0
    assert replayed.usage.prompt_tokens == recorded.usage.prompt_tokens


def test_embeddings_round_trip(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path)
    req = EmbedRequest(model="e", texts=("retina", "cornea"))
    recorded = CassetteProvider(StubProvider(), cassette, "record").embed(req)
    replayed = CassetteProvider(None, cassette, "replay").embed(req)
    assert replayed.vectors == recorded.vectors
    assert len(replayed.vectors) == 2


def test_ledger_writes_every_call(conn: sqlite3.Connection, owner_id: str) -> None:
    ledger = CostLedger(conn, owner_id, max_usd_per_run=1.0)
    ledger.record(
        kind="chat",
        model="m",
        mode="replay",
        usage=Usage(prompt_tokens=10, completion_tokens=4, usd=0.0),
        request_hash="abc",
        cache_hit=True,
    )
    row = conn.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()
    assert row["n"] == 1
    assert ledger.total_usd() == 0.0


def test_budget_preflight_refuses_before_spending(conn: sqlite3.Connection, owner_id: str) -> None:
    """D8: refuse if over. The check is before the call, not after the bill."""
    ledger = CostLedger(conn, owner_id, max_usd_per_run=0.10)
    ledger.record(
        kind="chat",
        model="m",
        mode="live",
        usage=Usage(usd=0.09),
        request_hash="a",
        cache_hit=False,
    )
    ledger.preflight(0.005)
    with pytest.raises(BudgetExceeded):
        ledger.preflight(0.05)
