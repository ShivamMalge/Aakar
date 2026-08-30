"""Per-owner question quota (2B.10).

The budget preflight is **global**: one user in a loop drains it for everyone, and every
other student then sees an exhausted budget they did nothing to cause. A per-owner daily
quota is the missing half.

**Two separate checks, and both must pass.** They are not alternatives and neither subsumes
the other:

* the **global budget** protects the operator from the total bill;
* the **per-owner quota** protects every other user from any one user.

A global budget alone permits one account to consume everything. A per-owner quota alone
permits N accounts to consume N times the intended total.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


class QuotaExceeded(RuntimeError):
    """One owner has had their share for today. Deliberately not `BudgetExceeded`.

    Separate types because the recoveries differ: a quota resets at midnight and affects
    one person; an exhausted budget affects everyone and needs an operator decision. One
    shared exception would force the UI to guess which had happened.
    """

    def __init__(self, message: str, *, remedy: str) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy


@dataclass(frozen=True)
class OwnerQuota:
    """Generous for study, finite for a loop.

    ``max_questions_per_day`` — **100**. A student working through a chapter asks tens of
    questions, not hundreds, so 100 is well beyond honest use while still bounding one
    account to a knowable slice of the daily budget. A count rather than a spend, because a
    student cannot reason about dollars and a count is the thing they can feel.
    """

    max_questions_per_day: int = 100

    @staticmethod
    def from_env() -> OwnerQuota:
        return OwnerQuota(
            max_questions_per_day=int(os.environ.get("AAKAR_MAX_QUESTIONS_PER_DAY", "100"))
        )


def questions_today(conn: sqlite3.Connection, owner_id: str, *, now: datetime | None = None) -> int:
    """Billable questions only.

    A cache hit is not a question against the quota: it cost nothing, and charging for it
    would penalise exactly the behaviour the cache design encourages.
    """
    today = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM llm_calls
        WHERE owner_id = ? AND tier = 'answer' AND cache_hit = 0 AND date(created_at) = ?
        """,
        (owner_id, today),
    ).fetchone()
    return int(row["n"])


def check_owner_quota(
    conn: sqlite3.Connection,
    owner_id: str,
    quota: OwnerQuota | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """Raise if this owner has spent their day. Checked before the call, like the budget."""
    quota = quota or OwnerQuota.from_env()
    asked = questions_today(conn, owner_id, now=now)
    if asked >= quota.max_questions_per_day:
        raise QuotaExceeded(
            f"you have asked {asked} questions today; the daily limit is "
            f"{quota.max_questions_per_day}",
            remedy=(
                "Your limit resets at midnight UTC. Cached answers and the topic library "
                "keep working in the meantime."
            ),
        )
