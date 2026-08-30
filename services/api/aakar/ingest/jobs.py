"""The ingest queue (D-034), and the global bounds that keep it finite.

`max_ocr_pages` of 40 at ~25 s/page is ~17 minutes for one upload. No HTTP request
survives that, so ingest cannot be request/response.

**The split that matters: rejection is synchronous, work is asynchronous.** Every boundary
check — size, page count, OCR page count, encryption, per-owner quota, and the global
bounds below — runs before the response, so a student who uploads something unacceptable
finds out at upload. Only accepted work is queued. A rejection that arrives seventeen
minutes later is a worse product than one that arrives immediately, and an unbounded queue
turns a rejection into a resource commitment that merely happens later.

## Global bounds — proposed, with reasoning

Per-owner quotas stop one user hurting everyone; they do nothing about fifty users doing it
collectively. At the approved 400 pages/day against a 500-account ceiling that is ~200,000
pages/day, roughly **1,400 CPU-hours** — about 58 machine-days of work per day.

* ``max_concurrent_ocr`` — **2**. The binding resource is CPU, and OCR is CPU-bound, so
  useful concurrency is bounded by cores, not by patience. Two leaves headroom for the API
  and the worker's own overhead on a small box. Raising it does not increase throughput on
  a machine that is already saturated; it only lengthens every job at once, which turns one
  slow upload into several.
* ``max_queue_depth`` — **50**. At two concurrent jobs and a 17-minute worst case, a full
  queue is ~7 hours of backlog. Beyond that a queued job is indistinguishable from a lost
  one, and the honest answer is to refuse it. Queue-full is rejected **at submission**, with
  the depth in the message, so the uploader can retry rather than wait on a promise.

Both are configurable; both default low, because the cost of a too-low bound is a visible
rejection and the cost of a too-high one is a queue nobody drains.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from aakar.db import new_id

from .limits import IngestRejected, RejectionCode


@dataclass(frozen=True)
class GlobalBounds:
    """System-wide ceilings. See the module docstring for how the numbers were chosen."""

    max_concurrent_ocr: int = 2
    max_queue_depth: int = 50


GLOBAL_DEFAULTS = GlobalBounds()

#: Terminal states. A job in one of these is not coming back.
FINISHED = ("succeeded", "failed", "rejected")


@dataclass(frozen=True)
class Job:
    id: str
    document_id: str
    owner_id: str
    status: str
    pages_done: int
    pages_total: int
    failure_reason: str | None = None

    @property
    def progress(self) -> float:
        """Real progress, from pages actually completed. Never interpolated from time."""
        return 0.0 if self.pages_total == 0 else self.pages_done / self.pages_total


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def check_global_bounds(conn: sqlite3.Connection, bounds: GlobalBounds = GLOBAL_DEFAULTS) -> None:
    """Refuse at submission when the system as a whole is full.

    Counted over every owner, which is the entire point: the per-owner quota cannot see
    this, because no single owner is doing anything wrong.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ingest_jobs WHERE status IN ('queued','running')"
    ).fetchone()
    depth = int(row["n"])
    if depth >= bounds.max_queue_depth:
        raise IngestRejected(
            RejectionCode.QUEUE_FULL,
            f"the ingest queue is full ({depth} jobs waiting; the limit is "
            f"{bounds.max_queue_depth})",
            remedy="Too many documents are being processed right now. Try again later.",
        )


def enqueue(
    conn: sqlite3.Connection,
    document_id: str,
    owner_id: str,
    pages_total: int,
    bounds: GlobalBounds = GLOBAL_DEFAULTS,
) -> str:
    """Accept work onto the queue. Callers must have run the boundary checks first."""
    check_global_bounds(conn, bounds)
    job_id = new_id("job")
    conn.execute(
        """
        INSERT INTO ingest_jobs (id, document_id, owner_id, status, pages_done, pages_total)
        VALUES (?, ?, ?, 'queued', 0, ?)
        """,
        (job_id, document_id, owner_id, pages_total),
    )
    conn.commit()
    return job_id


def claim_next(conn: sqlite3.Connection, bounds: GlobalBounds = GLOBAL_DEFAULTS) -> Job | None:
    """Take the oldest queued job, if the concurrency bound allows. FIFO.

    The claim is a single conditional UPDATE, so two workers racing for the same row
    cannot both win: the second sees `rowcount == 0` and moves on. Cheap here because
    SQLite serialises writers anyway, and correct if that ever changes.
    """
    running = int(
        conn.execute("SELECT COUNT(*) AS n FROM ingest_jobs WHERE status = 'running'").fetchone()[
            "n"
        ]
    )
    if running >= bounds.max_concurrent_ocr:
        return None

    # ORDER BY created_at, rowid — not `id`. `created_at` has one-second resolution, so
    # jobs submitted in the same second tie, and `id` is a random uuid: the tiebreak was
    # arbitrary, which made "oldest first" untrue under exactly the load where FIFO
    # matters. `rowid` is monotonic in insertion order.
    row = conn.execute(
        "SELECT id FROM ingest_jobs WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1"
    ).fetchone()
    if row is None:
        return None

    cursor = conn.execute(
        "UPDATE ingest_jobs SET status = 'running', started_at = ? "
        "WHERE id = ? AND status = 'queued'",
        (_now(), row["id"]),
    )
    conn.commit()
    if cursor.rowcount == 0:
        return None  # another worker claimed it first
    return get_job(conn, str(row["id"]))


def record_progress(conn: sqlite3.Connection, job_id: str, pages_done: int) -> None:
    """Written as work completes (D-034), never derived from elapsed time."""
    conn.execute("UPDATE ingest_jobs SET pages_done = ? WHERE id = ?", (pages_done, job_id))
    conn.commit()


def finish(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    failure_reason: str | None = None,
) -> None:
    if status not in FINISHED:
        raise ValueError(f"{status!r} is not a terminal status")
    conn.execute(
        "UPDATE ingest_jobs SET status = ?, finished_at = ?, failure_reason = ? WHERE id = ?",
        (status, _now(), failure_reason, job_id),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute(
        "SELECT id, document_id, owner_id, status, pages_done, pages_total, failure_reason"
        " FROM ingest_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return Job(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        owner_id=str(row["owner_id"]),
        status=str(row["status"]),
        pages_done=int(row["pages_done"]),
        pages_total=int(row["pages_total"]),
        failure_reason=row["failure_reason"],
    )


def get_job_for_owner(conn: sqlite3.Connection, job_id: str, owner_id: str) -> Job | None:
    """Owner-scoped read. Returns None for another owner's job, so the route can 404.

    404 rather than 403: a 403 confirms the job exists, which tells an attacker whether an
    id is real.
    """
    job = get_job(conn, job_id)
    return job if job is not None and job.owner_id == owner_id else None


def queue_depth(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM ingest_jobs WHERE status IN ('queued','running')"
        ).fetchone()["n"]
    )
