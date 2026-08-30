"""D-034 — ingest is asynchronous, and rejection is not.

40 OCR pages at ~25 s/page is ~17 minutes for one upload. No HTTP request survives that,
so the work is queued. But the *checks* stay synchronous: a student who uploads something
unacceptable must find out at upload, not seventeen minutes later.

These tests assert both halves, and the global bounds that keep the queue finite.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pypdf
import pytest
from fastapi.testclient import TestClient

from aakar.app import create_app, get_settings
from aakar.auth import SESSION_COOKIE, ensure_owner, issue_session
from aakar.config import Settings
from aakar.db import init_db, new_id
from aakar.ingest import GlobalBounds, IngestRejected, RejectionCode, enqueue, get_job_for_owner
from aakar.ingest.jobs import claim_next, finish, queue_depth, record_progress
from aakar.ingest.worker import process_one

SECRET = "async-ingest-secret-at-least-32-bytes"


def make_pdf(pages: int = 3) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def client(db_path: Path, owner_id: str) -> TestClient:
    base = Settings.from_env()
    app = create_app()
    conn = init_db(db_path)
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{**base.__dict__, "db_path": db_path, "auth_secret": SECRET}
    )
    # Deliberately NOT overriding get_conn: TestClient runs the app in another thread, and
    # a shared sqlite3 connection is bound to the thread that made it. The real dependency
    # opens one per request, which is what production does too.
    conn.close()
    test_client = TestClient(app)
    test_client.cookies.set(SESSION_COOKIE, issue_session(owner_id, SECRET))
    return test_client


# ------------------------------------------------- rejection stays synchronous


def test_an_unacceptable_upload_is_refused_in_the_response(client: TestClient) -> None:
    """The whole point of D-034's split. No job is created for work that cannot run."""
    response = client.post(
        "/ingest/upload", files={"file": ("notes.txt", b"not a pdf at all", "application/pdf")}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == RejectionCode.UNPARSEABLE
    assert detail["remedy"], "a rejection without a remedy is a wall"


def test_a_rejected_upload_creates_no_job_and_no_document(
    client: TestClient, db_path: Path
) -> None:
    client.post("/ingest/upload", files={"file": ("x.pdf", b"garbage", "application/pdf")})
    conn = init_db(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM ingest_jobs").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 0
    conn.close()


def test_upload_requires_the_owner_session(db_path: Path, owner_id: str) -> None:
    app = create_app()
    anonymous = TestClient(app)
    assert (
        anonymous.post(
            "/ingest/upload", files={"file": ("x.pdf", make_pdf(1), "application/pdf")}
        ).status_code
        == 401
    )


# --------------------------------------------------- acceptance is a job, not a result


def test_an_accepted_upload_returns_202_and_a_job(client: TestClient) -> None:
    """202, not 200: nothing has been parsed yet, and 200 would say otherwise."""
    response = client.post(
        "/ingest/upload", files={"file": ("ch1.pdf", make_pdf(3), "application/pdf")}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] and body["document_id"] and body["corpus_id"]
    assert body["page_count"] == 3
    assert body["corpus_created"] is True


def test_the_job_starts_queued_with_real_totals(client: TestClient, db_path: Path) -> None:
    job_id = client.post(
        "/ingest/upload", files={"file": ("ch1.pdf", make_pdf(5), "application/pdf")}
    ).json()["job_id"]

    status = client.get(f"/ingest/jobs/{job_id}").json()
    assert status["status"] == "queued"
    assert status["pages_done"] == 0
    assert status["pages_total"] == 5


def test_a_second_owner_uploading_the_same_file_shares_the_corpus(
    client: TestClient, db_path: Path, owner_id: str
) -> None:
    data = make_pdf(2)
    first = client.post("/ingest/upload", files={"file": ("c.pdf", data, "application/pdf")}).json()

    conn = init_db(db_path)
    other = ensure_owner(conn, "other@example.com", "password-other-long-enough")
    client.cookies.set(SESSION_COOKIE, issue_session(other, SECRET))
    second = client.post(
        "/ingest/upload", files={"file": ("c.pdf", data, "application/pdf")}
    ).json()

    assert first["corpus_id"] == second["corpus_id"]
    assert first["corpus_created"] is True
    assert second["corpus_created"] is False
    assert first["document_id"] != second["document_id"]
    conn.close()


# ------------------------------------------------------------ status is owner-scoped


def test_another_owners_job_is_404_not_403(client: TestClient, db_path: Path) -> None:
    """403 would confirm the id is real, which is itself information."""
    job_id = client.post(
        "/ingest/upload", files={"file": ("c.pdf", make_pdf(1), "application/pdf")}
    ).json()["job_id"]

    conn = init_db(db_path)
    other = ensure_owner(conn, "other@example.com", "password-other-long-enough")
    client.cookies.set(SESSION_COOKIE, issue_session(other, SECRET))

    assert client.get(f"/ingest/jobs/{job_id}").status_code == 404
    assert client.get("/ingest/jobs/job_does_not_exist").status_code == 404
    conn.close()


def test_get_job_for_owner_refuses_across_owners(conn: sqlite3.Connection, owner_id: str) -> None:
    other = ensure_owner(conn, "other@example.com", "password-other-long-enough")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('d1', ?, 'c1', 'f.pdf', 'h1', '/x')",
        (owner_id,),
    )
    conn.commit()
    job_id = enqueue(conn, "d1", owner_id, 3)

    assert get_job_for_owner(conn, job_id, owner_id) is not None
    assert get_job_for_owner(conn, job_id, other) is None


# ------------------------------------------------------------- the global bounds


def _seed(conn: sqlite3.Connection, owner_id: str, n: int) -> list[str]:
    conn.execute("INSERT OR IGNORE INTO corpora (id, content_hash, name) VALUES ('c1','h1','x')")
    jobs = []
    for i in range(n):
        doc = new_id("doc")
        conn.execute(
            "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
            " storage_path) VALUES (?, ?, 'c1', 'f.pdf', ?, '/x')",
            (doc, owner_id, f"h{i}"),
        )
        jobs.append(enqueue(conn, doc, owner_id, 2, GlobalBounds(max_queue_depth=1000)))
    conn.commit()
    return jobs


def test_a_full_queue_is_refused_at_submission_not_accepted_into_a_backlog(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """An unbounded queue turns a rejection into a resource commitment that happens later."""
    bounds = GlobalBounds(max_queue_depth=3)
    _seed(conn, owner_id, 3)

    with pytest.raises(IngestRejected) as raised:
        _seed_one = new_id("doc")
        conn.execute(
            "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
            " storage_path) VALUES (?, ?, 'c1', 'f.pdf', 'hx', '/x')",
            (_seed_one, owner_id),
        )
        enqueue(conn, _seed_one, owner_id, 2, bounds)
    assert raised.value.code == RejectionCode.QUEUE_FULL
    assert "3" in raised.value.message, "the depth belongs in the message so a retry is informed"


def test_the_queue_bound_counts_every_owner_not_just_this_one(conn: sqlite3.Connection) -> None:
    """The point of a global bound: no single owner is doing anything wrong."""
    a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    _seed(conn, a, 2)
    _seed(conn, b, 1)

    assert queue_depth(conn) == 3
    doc = new_id("doc")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES (?, ?, 'c1', 'f.pdf', 'hz', '/x')",
        (doc, b),
    )
    with pytest.raises(IngestRejected):
        enqueue(conn, doc, b, 1, GlobalBounds(max_queue_depth=3))


def test_concurrency_is_bounded_so_the_cpu_is_not_oversubscribed(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    bounds = GlobalBounds(max_concurrent_ocr=2, max_queue_depth=100)
    _seed(conn, owner_id, 4)

    assert claim_next(conn, bounds) is not None
    assert claim_next(conn, bounds) is not None
    # Two are running; the third must wait however many are queued.
    assert claim_next(conn, bounds) is None


def test_finishing_a_job_frees_a_slot(conn: sqlite3.Connection, owner_id: str) -> None:
    """Guards the guard: a bound that never releases would pass the test above."""
    bounds = GlobalBounds(max_concurrent_ocr=1, max_queue_depth=100)
    _seed(conn, owner_id, 2)

    first = claim_next(conn, bounds)
    assert first is not None
    assert claim_next(conn, bounds) is None
    finish(conn, first.id, "succeeded")
    assert claim_next(conn, bounds) is not None


def test_the_queue_is_fifo(conn: sqlite3.Connection, owner_id: str) -> None:
    bounds = GlobalBounds(max_concurrent_ocr=5, max_queue_depth=100)
    jobs = _seed(conn, owner_id, 3)
    claimed = [claim_next(conn, bounds) for _ in range(3)]
    assert [j.id for j in claimed if j] == jobs


# ------------------------------------------------------------------- progress


def test_progress_is_real_not_interpolated(conn: sqlite3.Connection, owner_id: str) -> None:
    """pages_done is written as work completes (D-034). A bar that moves while nothing
    happens is worse than no bar."""
    jobs = _seed(conn, owner_id, 1)
    job_id = jobs[0]

    claim_next(conn, GlobalBounds(max_concurrent_ocr=1, max_queue_depth=100))
    job = get_job_for_owner(conn, job_id, owner_id)
    assert job is not None and job.pages_done == 0 and job.progress == 0.0

    record_progress(conn, job_id, 1)
    job = get_job_for_owner(conn, job_id, owner_id)
    assert job is not None and job.pages_done == 1 and job.progress == 0.5


def test_a_failed_job_stores_its_reason(conn: sqlite3.Connection, owner_id: str) -> None:
    job_id = _seed(conn, owner_id, 1)[0]
    finish(conn, job_id, "failed", failure_reason="unparseable: damaged page tree")
    job = get_job_for_owner(conn, job_id, owner_id)
    assert job is not None
    assert job.status == "failed"
    assert "damaged" in (job.failure_reason or "")


def test_finish_refuses_a_non_terminal_status(conn: sqlite3.Connection, owner_id: str) -> None:
    job_id = _seed(conn, owner_id, 1)[0]
    with pytest.raises(ValueError, match="terminal"):
        finish(conn, job_id, "running")


# ---------------------------------------------------------------- the worker


def test_the_worker_parses_a_queued_document_end_to_end(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """The whole async path, driven one job at a time so no thread is needed."""
    from aakar.ingest.chunks import load_chunks

    pdf = tmp_path / "ch1.pdf"
    pdf.write_bytes(_text_pdf())

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
        " page_count, storage_path) VALUES ('d1', ?, 'c1', 'ch1.pdf', 'h1', 1, ?)",
        (owner_id, str(pdf)),
    )
    conn.execute(
        "INSERT INTO document_pages (document_id, page_index, page_label) VALUES ('d1', 0, '1')"
    )
    conn.commit()
    job_id = enqueue(conn, "d1", owner_id, 1)

    assert process_one(conn, tmp_path) == job_id

    job = get_job_for_owner(conn, job_id, owner_id)
    assert job is not None
    assert job.status == "succeeded", job.failure_reason
    assert job.pages_done == job.pages_total == 1

    chunks = load_chunks(conn, "d1")
    assert chunks, "the parser produced no chunks"
    assert chunks[0].page.label == "1"
    # 2A.5, measured: block.source is the finest signal the parser offers.
    assert chunks[0].source == "digital"
    assert chunks[0].warning_scope == "none"

    tier = conn.execute("SELECT parse_tier FROM documents WHERE id='d1'").fetchone()["parse_tier"]
    assert tier == "digital"


def test_the_worker_records_a_failure_rather_than_dying(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """One bad document must not stop the queue."""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
        " page_count, storage_path) VALUES ('d1', ?, 'c1', 'bad.pdf', 'h1', 1, ?)",
        (owner_id, str(bad)),
    )
    conn.commit()
    job_id = enqueue(conn, "d1", owner_id, 1)

    assert process_one(conn, tmp_path) == job_id
    job = get_job_for_owner(conn, job_id, owner_id)
    assert job is not None and job.status == "failed"
    assert job.failure_reason


def test_the_worker_returns_none_when_the_queue_is_empty(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    assert process_one(conn, tmp_path) is None


def _text_pdf(text: str = "The lens focuses light onto the retina.") -> bytes:
    """A minimal PDF with a real text-showing operator, so the parser finds a block."""
    content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources"
            b" << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        ),
        (
            4,
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
        ),
        (5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in objs:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for i in range(1, len(objs) + 1):
        out += f"{offsets[i]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ------------------------------------------- the cross-thread connection fix


def test_a_connection_survives_the_dependency_to_async_endpoint_thread_hop(
    client: TestClient,
) -> None:
    """Confirming the fix, not noting it.

    FastAPI runs a *sync* dependency (`get_conn`) in a threadpool while an `async def`
    endpoint body runs on the event loop thread. A sqlite3 connection defaults to
    `check_same_thread=True` and raises `ProgrammingError` when used from a different
    thread than the one that opened it — so `/ingest/upload`, the first async endpoint in
    the project, could not touch the database at all.

    `connect()` now opens with `check_same_thread=False`. Each request still gets its own
    connection, so none is shared between threads concurrently; only the hop between the
    dependency and the body crosses a thread boundary.

    This test exercises the real route through TestClient, which runs the app in a
    separate thread — the same hop production has.
    """
    response = client.post(
        "/ingest/upload", files={"file": ("ch1.pdf", make_pdf(2), "application/pdf")}
    )
    assert response.status_code == 202, response.text

    # And the write is durable, i.e. the connection really worked rather than failing quietly.
    job = client.get(f"/ingest/jobs/{response.json()['job_id']}")
    assert job.status_code == 200
    assert job.json()["pages_total"] == 2


def test_repeated_requests_each_get_a_working_connection(client: TestClient) -> None:
    """Guards the guard: one lucky request would pass the test above."""
    for pages in (1, 2, 3):
        response = client.post(
            "/ingest/upload", files={"file": (f"c{pages}.pdf", make_pdf(pages), "application/pdf")}
        )
        assert response.status_code == 202, response.text
        assert response.json()["page_count"] == pages


# --------------------------------------------------- a corpus is never empty


def test_a_document_with_no_extractable_text_fails_rather_than_creating_an_empty_corpus(
    conn: sqlite3.Connection, owner_id: str, tmp_path: Path
) -> None:
    """An empty corpus looks ingested, retrieves nothing, and answers every question with
    "your chapter does not cover this" — indistinguishable, to the student, from a chapter
    that genuinely says nothing."""
    from aakar.ingest.chunks import load_chunks

    blank = tmp_path / "blank.pdf"
    blank.write_bytes(make_pdf(2))  # genuinely blank pages: nothing to extract, nothing to OCR

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
        " page_count, storage_path) VALUES ('d1', ?, 'c1', 'blank.pdf', 'h1', 2, ?)",
        (owner_id, str(blank)),
    )
    conn.commit()
    job_id = enqueue(conn, "d1", owner_id, 2)

    process_one(conn, tmp_path)
    job = get_job_for_owner(conn, job_id, owner_id)

    assert job is not None
    assert job.status == "failed", "an empty parse must not be reported as success"
    assert "no_extractable_text" in (job.failure_reason or "")
    assert load_chunks(conn, "d1") == []
