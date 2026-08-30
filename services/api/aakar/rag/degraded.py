"""Degraded mode (2B.11).

When the system cannot generate, it **does not 500**. Generation and uploads switch off;
the approved-topic library and every cached answer keep serving, because they cost nothing
and there is no reason to take them away.

## The causes are distinguished, per D-035

The ruling: "worker unavailable" and "budget exhausted" are different causes with different
recoveries, and one shared "unavailable" state would force the UI to guess.

===========================  ==========================  ==========================
reason                       what stops                  who resolves it
===========================  ==========================  ==========================
``budget_exhausted``         generation, new answers     the operator, or midnight
``provider_unavailable``     generation, new answers     nobody; it comes back
``worker_unavailable``       **uploads only**            the operator restarts it
===========================  ==========================  ==========================

``worker_unavailable`` is the one it would have been wrong to merge: it stops *uploads*
while leaving Q&A completely healthy, because answering a question needs no worker. Folding
it into a generic banner would tell a student their questions were unavailable when they
were not.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class DegradedReason(StrEnum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    WORKER_UNAVAILABLE = "worker_unavailable"


#: A job claimed but untouched for longer than this means nobody is draining the queue.
#: Well above the ~17-minute worst case, so a slow document is not mistaken for a dead
#: worker — the cost of a false alarm is telling users uploads are down when they are not.
WORKER_STALL_MINUTES = 45


@dataclass(frozen=True)
class ServiceState:
    """What works right now, and what does not."""

    reasons: tuple[DegradedReason, ...] = ()

    @property
    def healthy(self) -> bool:
        return not self.reasons

    @property
    def can_upload(self) -> bool:
        return DegradedReason.WORKER_UNAVAILABLE not in self.reasons

    @property
    def can_generate(self) -> bool:
        """Covers new answers and SceneSpec generation — anything that calls a model."""
        blocking = {DegradedReason.BUDGET_EXHAUSTED, DegradedReason.PROVIDER_UNAVAILABLE}
        return not (blocking & set(self.reasons))

    @property
    def can_serve_cached(self) -> bool:
        """Always true. Cached answers and the library cost nothing to serve."""
        return True

    def banner(self) -> str | None:
        """One sentence per cause, naming what is unavailable and why.

        Not a generic "something went wrong": a student who cannot upload but can still ask
        questions needs to be told exactly that.
        """
        if self.healthy:
            return None
        messages = {
            DegradedReason.BUDGET_EXHAUSTED: (
                "New answers are paused because today's usage limit has been reached. "
                "Your library and all previously answered questions still work."
            ),
            DegradedReason.PROVIDER_UNAVAILABLE: (
                "New answers are temporarily unavailable while the language model is "
                "unreachable. Your library and all previously answered questions still work."
            ),
            DegradedReason.WORKER_UNAVAILABLE: (
                "New uploads are paused because documents are not being processed right "
                "now. Everything already in your library still works, including questions."
            ),
        }
        return " ".join(messages[reason] for reason in self.reasons)


def assess(
    conn: sqlite3.Connection,
    *,
    budget_exhausted: bool = False,
    provider_available: bool = True,
    now: datetime | None = None,
) -> ServiceState:
    """Work out what is degraded. Cheap enough to call per request."""
    reasons: list[DegradedReason] = []

    if budget_exhausted:
        reasons.append(DegradedReason.BUDGET_EXHAUSTED)
    if not provider_available:
        reasons.append(DegradedReason.PROVIDER_UNAVAILABLE)

    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=WORKER_STALL_MINUTES)
    stalled = conn.execute(
        "SELECT COUNT(*) AS n FROM ingest_jobs WHERE status = 'running' AND started_at < ?",
        (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
    ).fetchone()
    if int(stalled["n"]) > 0:
        reasons.append(DegradedReason.WORKER_UNAVAILABLE)

    return ServiceState(reasons=tuple(reasons))
