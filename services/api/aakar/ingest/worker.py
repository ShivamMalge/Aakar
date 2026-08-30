"""The ingest worker (D-034).

A separate process from the API, because the work it does is minutes long and CPU-bound.
Running it inside the API would block a request thread for the whole parse and make the
17-minute worst case an HTTP timeout instead of a job.

**Deployment consequence, recorded rather than discovered: this component cannot be
serverless.** It needs a persistent process that outlives any request. See D-035.

The loop is deliberately dull: claim one job, do it, record what happened, repeat. No
retries, because a parse that failed on a malformed PDF will fail again and a retry only
delays the honest answer; a job that fails is finished, with its reason stored.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

import structlog

from .chunks import Chunk, store_chunks
from .jobs import (
    EMPTY_REASON,
    GLOBAL_DEFAULTS,
    TIMEOUT_REASON,
    GlobalBounds,
    claim_next,
    finish,
    record_progress,
)
from .limits import IngestRejected
from .pages import PageMap
from .parser import parse_isolated, to_chunks

log = structlog.get_logger()


def process_one(
    conn: sqlite3.Connection,
    storage_root: Path,
    bounds: GlobalBounds = GLOBAL_DEFAULTS,
    *,
    indexer: Callable[[list[Chunk]], int] | None = None,
) -> str | None:
    """Claim and run a single job. Returns the job id, or None when there is nothing to do.

    Split out from the loop so a test can drive exactly one job without a thread.
    """
    job = claim_next(conn, bounds)
    if job is None:
        return None

    row = conn.execute(
        "SELECT storage_path, corpus_id, page_count FROM documents WHERE id = ?",
        (job.document_id,),
    ).fetchone()
    if row is None:
        finish(conn, job.id, "failed", failure_reason="the document row disappeared")
        return job.id

    try:
        # Killable subprocess under a wall clock (D-042). `max_ocr_pages` bounds pages;
        # this bounds time, which is the thing a pathological document actually consumes.
        parsed = parse_isolated(Path(str(row["storage_path"])), bounds.max_job_seconds)

        labels = [
            str(r["page_label"])
            for r in conn.execute(
                "SELECT page_label FROM document_pages WHERE document_id = ? ORDER BY page_index",
                (job.document_id,),
            )
        ]
        page_map = PageMap(labels or [str(i + 1) for i in range(max(parsed.page_count, 1))])

        chunks = to_chunks(
            parsed, page_map, document_id=job.document_id, corpus_id=str(row["corpus_id"])
        )

        # A corpus with zero chunks must never be created silently. An empty corpus looks
        # ingested, retrieves nothing, and produces "your chapter does not cover this" for
        # every question — which is indistinguishable, to the student, from a chapter that
        # genuinely says nothing. Fail loudly instead.
        if not chunks:
            finish(
                conn,
                job.id,
                "failed",
                failure_reason=(
                    f"{EMPTY_REASON}: this document produced no readable text "
                    f"(parser tier: {parsed.tier}). If it is a scan, the pages may be "
                    f"blank or unreadable."
                ),
            )
            log.warning("ingest.empty", job=job.id, tier=parsed.tier)
            return job.id

        # Progress is written as pages complete, never interpolated (D-034). Chunks are
        # grouped by page so the number reported is a number of pages actually finished.
        by_page: dict[int, list[Chunk]] = {}
        for chunk in chunks:
            by_page.setdefault(chunk.page.index, []).append(chunk)

        for done, page_index in enumerate(sorted(by_page), start=1):
            store_chunks(conn, by_page[page_index])
            record_progress(conn, job.id, done)

        # Embedding and indexing happen INSIDE the job, after chunks are stored, so a
        # failure here fails the job rather than leaving a document that is chunked but
        # unsearchable — which would answer every question with "not in your chapter".
        if indexer is not None:
            indexed = indexer(chunks)
            log.info("ingest.indexed", job=job.id, vectors=indexed)

        conn.execute(
            "UPDATE documents SET parse_tier = ?, parse_warnings_json = ? WHERE id = ?",
            (parsed.tier, json.dumps(list(parsed.warnings)), job.document_id),
        )
        conn.commit()
        finish(conn, job.id, "succeeded")
        log.info("ingest.succeeded", job=job.id, chunks=len(chunks), tier=parsed.tier)

    except subprocess.TimeoutExpired:
        # Distinguished from a parse failure on purpose: the document may be perfectly
        # valid and merely slow, so "could not be read" would be a false statement. Only
        # this one is worth retrying on a quieter system.
        #
        # Nothing was written — chunks are stored inside the try, after the parse returns —
        # so there is no partial corpus to clean up. Same rule as no_extractable_text: a
        # half-ingested chapter that looks ingested is worse than a clean failure.
        finish(
            conn,
            job.id,
            "failed",
            failure_reason=(
                f"{TIMEOUT_REASON}: this document took longer than "
                f"{bounds.max_job_seconds}s to process and was stopped"
            ),
        )
        log.warning("ingest.timeout", job=job.id, seconds=bounds.max_job_seconds)
    except IngestRejected as rejected:
        # A parser-side refusal reaches the queue as a failure with the same vocabulary the
        # boundary uses, so the status endpoint can show one kind of message.
        finish(conn, job.id, "failed", failure_reason=f"{rejected.code}: {rejected.message}")
        log.warning("ingest.rejected", job=job.id, code=str(rejected.code))
    except Exception as exc:  # noqa: BLE001 - one bad document must not stop the worker
        finish(conn, job.id, "failed", failure_reason=f"unexpected: {exc}")
        log.exception("ingest.failed", job=job.id)

    return job.id


def drain(
    conn: sqlite3.Connection,
    storage_root: Path,
    bounds: GlobalBounds = GLOBAL_DEFAULTS,
    *,
    indexer: Callable[[list[Chunk]], int] | None = None,
) -> int:
    """Run every claimable job, then return. Used by tests and by a one-shot invocation."""
    processed = 0
    while process_one(conn, storage_root, bounds, indexer=indexer) is not None:
        processed += 1
    return processed
