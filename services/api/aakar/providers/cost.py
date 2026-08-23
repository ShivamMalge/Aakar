"""Cost log and the AAKAR_MAX_USD_PER_RUN kill switch (D8)."""

from __future__ import annotations

import sqlite3

from aakar.db import new_id

from .base import BudgetExceeded, Usage


class CostLedger:
    """Writes every call to llm_calls and refuses to cross the per-run budget.

    The check is *before* the call: a run that would exceed the cap raises rather than
    spending and then reporting. Replayed calls cost nothing and are logged with usd=0
    so that `llm_calls` stays a truthful record of what was actually spent.
    """

    def __init__(self, conn: sqlite3.Connection, owner_id: str, max_usd_per_run: float) -> None:
        self._conn = conn
        self._owner_id = owner_id
        self._max_usd = max_usd_per_run
        self._spent = 0.0

    @property
    def spent(self) -> float:
        return self._spent

    def preflight(self, projected_usd: float) -> None:
        """Print-before-you-spend check (D8). Raises rather than truncating a batch."""
        if self._spent + projected_usd > self._max_usd:
            raise BudgetExceeded(
                f"run would reach ${self._spent + projected_usd:.4f}, "
                f"over AAKAR_MAX_USD_PER_RUN=${self._max_usd:.2f}"
            )

    def record(
        self,
        *,
        kind: str,
        model: str,
        mode: str,
        usage: Usage,
        request_hash: str,
        cache_hit: bool,
        topic_id: str | None = None,
    ) -> None:
        self._spent += usage.usd
        self._conn.execute(
            """
            INSERT INTO llm_calls (id, owner_id, kind, model, mode, cache_hit,
                                   prompt_tokens, completion_tokens, usd, topic_id, request_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("call"),
                self._owner_id,
                kind,
                model,
                mode,
                int(cache_hit),
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.usd,
                topic_id,
                request_hash,
            ),
        )
        self._conn.commit()

    def total_usd(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(usd), 0.0) AS t FROM llm_calls WHERE owner_id = ?",
            (self._owner_id,),
        ).fetchone()
        return float(row["t"])
