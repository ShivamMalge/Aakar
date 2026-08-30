"""Registration ceiling (2B.12).

A config flag capping total accounts, with a waitlist beyond it. **Default low.**

Every protection built so far is per-owner or global-per-day. None of them bounds the
number of owners, and the ingest arithmetic only holds at a stated account count: the
global bound in D-037 was reasoned against 500 accounts, so the account count has to be
something the system controls rather than something it discovers.

Beyond the ceiling a signup is **waitlisted, not refused**. A refusal loses the person; a
waitlist records them and costs one row.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from aakar.db import new_id


@dataclass(frozen=True)
class RegistrationPolicy:
    """``max_accounts`` — **25** by default.

    Deliberately far below the 500 the ingest bounds were reasoned against: the ceiling is
    a thing to raise deliberately once the numbers are measured, not a thing to discover by
    being overrun. Raising it is one environment variable.
    """

    max_accounts: int = 25

    @staticmethod
    def from_env() -> RegistrationPolicy:
        return RegistrationPolicy(max_accounts=int(os.environ.get("AAKAR_MAX_ACCOUNTS", "25")))


def account_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


def has_capacity(conn: sqlite3.Connection, policy: RegistrationPolicy | None = None) -> bool:
    policy = policy or RegistrationPolicy.from_env()
    return account_count(conn) < policy.max_accounts


def register_or_waitlist(
    conn: sqlite3.Connection, email: str, policy: RegistrationPolicy | None = None
) -> tuple[bool, int | None]:
    """Returns ``(admitted, waitlist_position)``.

    ``(True, None)`` when there is room. Otherwise ``(False, position)`` — 1-based, and
    stable, so someone can be told where they are rather than only that they are waiting.
    Re-registering the same address returns the existing position instead of adding a
    second row.
    """
    policy = policy or RegistrationPolicy.from_env()
    if has_capacity(conn, policy):
        return True, None

    existing = conn.execute("SELECT position FROM waitlist WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        return False, int(existing["position"])

    row = conn.execute("SELECT COALESCE(MAX(position), 0) AS p FROM waitlist").fetchone()
    position = int(row["p"]) + 1
    conn.execute(
        "INSERT INTO waitlist (id, email, position) VALUES (?, ?, ?)",
        (new_id("wait"), email, position),
    )
    conn.commit()
    return False, position
