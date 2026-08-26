"""Record/replay cassette (D8). Modes: live | record | replay.

All tests and CI run in `replay`, so the suite never needs a key and never spends money.
A replay miss is a hard error rather than a silent fallthrough to `live` — a test that
quietly started calling a real API would be worse than a failing one.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .base import (
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    Provider,
    Usage,
    VlmRequest,
    request_hash,
)
from .cost import CostLedger

#: Charged against the cap before a call, since the true cost is unknown until it returns.
#: Pessimistic on purpose: an estimate that is too low re-opens the hole the guard closes.
DEFAULT_ESTIMATE_USD = 0.05

#: The cassette keys on "embed"; `llm_calls.kind` is constrained to "embedding". Mapped
#: here rather than loosening the CHECK, which is what keeps the ledger's vocabulary
#: closed — a typo'd kind should fail the insert, not quietly create a new category.
LEDGER_KIND = {"chat": "chat", "vlm": "vlm", "embed": "embedding"}


class CassetteMiss(RuntimeError):
    """Replay mode was asked for a request the cassette has never seen."""


class Cassette:
    """One JSON file per request hash, under cassette_dir/<kind>/<hash>.json."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, kind: str, key: str) -> Path:
        return self._root / kind / f"{key}.json"

    def read(self, kind: str, key: str) -> dict[str, object] | None:
        path = self._path(kind, key)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        return data

    def write(self, kind: str, key: str, payload: dict[str, object]) -> None:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class CassetteProvider:
    """Wraps a real provider with record/replay.

    In `replay` the inner provider is never constructed or called, which is what lets CI
    run with no API key at all.
    """

    def __init__(
        self,
        inner: Provider | None,
        cassette: Cassette,
        mode: str,
        ledger: CostLedger | None = None,
        *,
        estimate_usd: float = DEFAULT_ESTIMATE_USD,
        topic_id: str | None = None,
    ) -> None:
        """`ledger` wires the D8 budget guard into the only path that can spend money.

        Optional, and deliberately so: Phase 0/1 construct providers in tests where there
        is no database. `require_ledger` at the call site is what makes it non-optional in
        production; here it is enough that *when* a ledger is supplied, no call can slip
        past it.

        `estimate_usd` is what the preflight charges against the cap **before** the call,
        since the true cost is not known until the response comes back. It is deliberately
        a pessimistic flat rate rather than a model of token pricing — a guess that is too
        low re-opens the hole the guard exists to close, and the ledger records the real
        figure afterwards either way.
        """
        if mode not in {"live", "record", "replay"}:
            raise ValueError(f"unknown mode {mode!r}")
        if mode != "replay" and inner is None:
            raise ValueError(f"mode {mode!r} needs an inner provider")
        self._inner = inner
        self._cassette = cassette
        self._mode = mode
        self._ledger = ledger
        self._estimate_usd = estimate_usd
        self._topic_id = topic_id
        self.last_was_cache_hit = False

    @property
    def mode(self) -> str:
        return self._mode

    def _dispatch(
        self,
        kind: str,
        req: ChatRequest | VlmRequest | EmbedRequest,
    ) -> dict[str, object]:
        key = request_hash(kind, req)

        if self._mode in {"replay", "record"}:
            cached = self._cassette.read(kind, key)
            if cached is not None:
                self.last_was_cache_hit = True
                return cached
            if self._mode == "replay":
                raise CassetteMiss(
                    f"no cassette for {kind}:{key}. Re-record with "
                    f"AAKAR_PROVIDER_MODE=record, or fix the request that drifted."
                )

        # Everything below this line can spend money, so the guard goes here — after the
        # cassette has had its chance, before the provider is touched. A replayed call and
        # a recorded hit both return above and cost nothing, so neither consumes budget.
        if self._ledger is not None:
            self._ledger.preflight(self._estimate_usd)

        assert self._inner is not None  # guarded in __init__ for non-replay modes
        self.last_was_cache_hit = False

        if isinstance(req, ChatRequest):
            resp = self._inner.chat(req)
            payload: dict[str, object] = {"text": resp.text, "usage": asdict(resp.usage)}
        elif isinstance(req, VlmRequest):
            resp = self._inner.vlm(req)
            payload = {"text": resp.text, "usage": asdict(resp.usage)}
        else:
            emb = self._inner.embed(req)
            payload = {
                "vectors": [list(v) for v in emb.vectors],
                "usage": asdict(emb.usage),
            }

        if self._mode == "record":
            self._cassette.write(kind, key, payload)
        return payload

    @staticmethod
    def _usage(payload: dict[str, object], *, replayed: bool) -> Usage:
        raw = payload.get("usage") or {}
        assert isinstance(raw, dict)
        # A replayed call spends nothing, whatever the recording cost at the time.
        return Usage(
            prompt_tokens=int(raw.get("prompt_tokens", 0)),
            completion_tokens=int(raw.get("completion_tokens", 0)),
            usd=0.0 if replayed else float(raw.get("usd", 0.0)),
        )

    def _record(
        self, kind: str, req: ChatRequest | VlmRequest | EmbedRequest, usage: Usage
    ) -> None:
        """Every call reaches the ledger, hit or miss.

        Replayed and cached calls are logged with usd=0 rather than skipped: `llm_calls`
        is meant to be a truthful record of what happened, and a cache hit that left no
        trace would make the hit rate unmeasurable in Phase 2B.
        """
        if self._ledger is None:
            return
        self._ledger.record(
            kind=LEDGER_KIND[kind],
            model=req.model,
            mode=self._mode,
            usage=usage,
            request_hash=request_hash(kind, req),
            cache_hit=self.last_was_cache_hit,
            topic_id=self._topic_id,
        )

    def chat(self, req: ChatRequest) -> ChatResponse:
        payload = self._dispatch("chat", req)
        usage = self._usage(payload, replayed=self.last_was_cache_hit)
        self._record("chat", req, usage)
        return ChatResponse(text=str(payload["text"]), usage=usage)

    def vlm(self, req: VlmRequest) -> ChatResponse:
        payload = self._dispatch("vlm", req)
        usage = self._usage(payload, replayed=self.last_was_cache_hit)
        self._record("vlm", req, usage)
        return ChatResponse(text=str(payload["text"]), usage=usage)

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        payload = self._dispatch("embed", req)
        raw = payload["vectors"]
        assert isinstance(raw, list)
        vectors = tuple(tuple(float(x) for x in v) for v in raw)
        usage = self._usage(payload, replayed=self.last_was_cache_hit)
        self._record("embed", req, usage)
        return EmbedResponse(vectors=vectors, usage=usage)
