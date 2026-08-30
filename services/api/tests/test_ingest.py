"""Phase 2A ingest boundary: limits, rejection, dedupe, page spaces.

The limits exist because LightningParse OCR runs at ~25 s/page: a 400-page scan is roughly
three CPU-hours for one upload **with no LLM call**, so no budget guard fires. This is a
denial-of-service surface, and the only place to stop it is before any work begins.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import UTC, datetime, timedelta

import pypdf
import pytest

from aakar.ingest import (
    IngestLimits,
    IngestRejected,
    PageMap,
    PageRef,
    RejectionCode,
    can_read,
    check_file,
    check_quota,
    content_hash,
    resolve_corpus,
)
from aakar.ingest.chunks import Chunk, load_chunks, store_chunks, warning_summary


def make_pdf(pages: int = 3) -> bytes:
    """A real PDF, built in memory. Fixtures on disk would drift from the reader.

    Blank pages have no text layer, which is exactly what makes them useful here: they
    count as OCR work, so the expensive limit can be exercised without shipping a scan.
    """
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ rejection


def test_an_empty_upload_is_refused() -> None:
    with pytest.raises(IngestRejected) as raised:
        check_file(b"")
    assert raised.value.code == RejectionCode.EMPTY
    assert raised.value.remedy


def test_a_non_pdf_is_refused_with_a_reason_not_a_crash() -> None:
    """2A.4: explicit rejection. Not a traceback, and not a silent OCR fallback."""
    with pytest.raises(IngestRejected) as raised:
        check_file(b"this is not a PDF at all, it is a text file")
    assert raised.value.code == RejectionCode.UNPARSEABLE
    assert "PDF" in raised.value.message
    assert raised.value.remedy


def test_a_truncated_pdf_is_refused() -> None:
    data = make_pdf(2)[: len(make_pdf(2)) // 3]
    with pytest.raises(IngestRejected) as raised:
        check_file(data)
    assert raised.value.code in {RejectionCode.UNPARSEABLE, RejectionCode.EMPTY}


def test_an_encrypted_pdf_is_refused_with_an_actionable_remedy() -> None:
    """2A.4. The remedy matters: "encrypted" alone leaves the uploader stuck."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("a-password")
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(IngestRejected) as raised:
        check_file(buffer.getvalue())
    assert raised.value.code == RejectionCode.ENCRYPTED
    assert "password" in raised.value.remedy.lower()


def test_every_rejection_carries_a_remedy() -> None:
    """A rejection without one is a wall, and the uploader has no next move."""
    cases: list[bytes] = [b"", b"not a pdf"]
    for data in cases:
        with pytest.raises(IngestRejected) as raised:
            check_file(data)
        assert raised.value.remedy.strip(), f"{raised.value.code} has no remedy"


# --------------------------------------------------------------------- limits


def test_an_oversized_file_is_refused_before_it_is_parsed() -> None:
    """Checked first because it costs nothing: no parse, no page walk, no OCR estimate."""
    limits = IngestLimits(max_bytes=1024)
    with pytest.raises(IngestRejected) as raised:
        check_file(b"x" * 2048, limits)
    assert raised.value.code == RejectionCode.TOO_LARGE
    # It never reached the parser, which would have said UNPARSEABLE for these bytes.
    assert "MB" in raised.value.message


def test_too_many_pages_is_refused() -> None:
    limits = IngestLimits(max_pages=2)
    with pytest.raises(IngestRejected) as raised:
        check_file(make_pdf(5), limits)
    assert raised.value.code == RejectionCode.TOO_MANY_PAGES


def test_too_many_ocr_pages_is_refused() -> None:
    """The expensive limit. Blank pages have no text layer, so they count as OCR work."""
    limits = IngestLimits(max_pages=100, max_ocr_pages=2)
    with pytest.raises(IngestRejected) as raised:
        check_file(make_pdf(5), limits)
    assert raised.value.code == RejectionCode.TOO_MANY_OCR_PAGES
    assert "25 s" in raised.value.remedy or "selectable text" in raised.value.remedy


def test_a_document_within_every_limit_is_accepted() -> None:
    """Guards the guard: limits that refuse everything pass the tests above just as well."""
    facts = check_file(make_pdf(3), IngestLimits(max_pages=10, max_ocr_pages=10))
    assert facts.page_count == 3
    assert len(facts.page_labels) == 3


# --------------------------------------------------------------------- quotas


def _accept_document(conn: sqlite3.Connection, owner: str, doc: str, pages: int, when: str) -> None:
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
        " page_count, storage_path, created_at) VALUES (?, ?, 'c1', 'f.pdf', ?, ?, '/x', ?)",
        (doc, owner, doc, pages, when),
    )
    conn.commit()


def test_the_daily_document_quota_refuses_at_the_limit(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    now = datetime.now(UTC)
    limits = IngestLimits(max_documents_per_day=2, max_pages_per_day=1000)

    for i in range(2):
        _accept_document(conn, owner_id, f"d{i}", 1, now.strftime("%Y-%m-%d %H:%M:%S"))

    with pytest.raises(IngestRejected) as raised:
        check_quota(conn, owner_id, incoming_pages=1, limits=limits, now=now)
    assert raised.value.code == RejectionCode.QUOTA_DOCUMENTS


def test_the_daily_page_quota_counts_the_incoming_document(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """Counted before acceptance, or the limit is only ever discovered after the work."""
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    now = datetime.now(UTC)
    limits = IngestLimits(max_documents_per_day=100, max_pages_per_day=50)
    _accept_document(conn, owner_id, "d0", 40, now.strftime("%Y-%m-%d %H:%M:%S"))

    check_quota(conn, owner_id, incoming_pages=10, limits=limits, now=now)  # exactly 50
    with pytest.raises(IngestRejected) as raised:
        check_quota(conn, owner_id, incoming_pages=11, limits=limits, now=now)
    assert raised.value.code == RejectionCode.QUOTA_PAGES


def test_yesterdays_uploads_do_not_count_against_today(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    now = datetime.now(UTC)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    limits = IngestLimits(max_documents_per_day=1, max_pages_per_day=10)

    _accept_document(conn, owner_id, "old", 9, yesterday)
    check_quota(conn, owner_id, incoming_pages=9, limits=limits, now=now)


def test_one_owners_quota_does_not_bind_another(conn: sqlite3.Connection) -> None:
    from aakar.auth import ensure_owner

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    now = datetime.now(UTC)
    limits = IngestLimits(max_documents_per_day=1, max_pages_per_day=10)

    _accept_document(conn, a, "da", 9, now.strftime("%Y-%m-%d %H:%M:%S"))
    with pytest.raises(IngestRejected):
        check_quota(conn, a, incoming_pages=1, limits=limits, now=now)
    check_quota(conn, b, incoming_pages=9, limits=limits, now=now)  # unaffected


# ------------------------------------------------------- page label vs index


def test_a_page_ref_carries_both_spaces() -> None:
    ref = PageRef(index=0, label="vii")
    assert ref.index == 0
    assert ref.label == "vii"
    # D6 renders the label. "[p. 1]" here would be wrong in a way a reader cannot detect.
    assert ref.citation == "[p. vii]"


def test_label_and_index_diverge_with_front_matter() -> None:
    page_map = PageMap(["i", "ii", "iii", "1", "2"])
    assert page_map.diverges
    assert page_map.ref(0).label == "i"
    assert page_map.ref(3).label == "1"
    # The third body page is index 3, not index 1. Inferring one from the other is the
    # specific failure 2A.6 exists to prevent.
    assert page_map.ref(3).index != int(page_map.ref(3).label)


def test_labels_are_not_unique_so_lookup_returns_every_match() -> None:
    """A two-volume PDF restarts numbering. A label-to-index dict would lose pages."""
    page_map = PageMap(["1", "2", "1", "2"])
    assert page_map.indices_for_label("1") == (0, 2)


def test_a_plain_document_does_not_diverge() -> None:
    assert not PageMap(["1", "2", "3"]).diverges


def test_an_empty_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty label"):
        PageRef(index=0, label="")


def test_page_labels_are_read_from_the_pdf() -> None:
    facts = check_file(make_pdf(3), IngestLimits(max_ocr_pages=10))
    assert len(facts.page_labels) == facts.page_count
    PageMap(facts.page_labels)  # must be constructible, i.e. no empty labels


# ---------------------------------------------------------------- dedupe


def test_identical_bytes_hash_identically() -> None:
    assert content_hash(b"same") == content_hash(b"same")
    assert content_hash(b"same") != content_hash(b"different")


def test_two_owners_uploading_the_same_file_share_one_corpus(conn: sqlite3.Connection) -> None:
    from aakar.auth import ensure_owner

    a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    data = make_pdf(2)

    first = resolve_corpus(conn, a, data, "OpenStax ch.1")
    second = resolve_corpus(conn, b, data, "OpenStax ch.1")

    assert first.corpus_id == second.corpus_id
    assert first.created is True
    assert second.created is False, "the second upload re-parsed a corpus that existed"
    assert first.granted and second.granted
    assert can_read(conn, a, first.corpus_id) and can_read(conn, b, first.corpus_id)


def test_different_files_never_share_a_corpus(conn: sqlite3.Connection) -> None:
    """The whole isolation argument: sharing keys on the bytes, so nothing else can."""
    from aakar.auth import ensure_owner

    a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    b = ensure_owner(conn, "b@example.com", "password-b-long-enough")

    private = resolve_corpus(conn, a, make_pdf(2), "Private")
    other = resolve_corpus(conn, b, make_pdf(3), "Other")

    assert private.corpus_id != other.corpus_id
    assert not can_read(conn, b, private.corpus_id)
    assert not can_read(conn, a, other.corpus_id)


def test_re_uploading_your_own_file_is_idempotent(conn: sqlite3.Connection, owner_id: str) -> None:
    data = make_pdf(2)
    first = resolve_corpus(conn, owner_id, data, "Chapter")
    second = resolve_corpus(conn, owner_id, data, "Chapter")

    assert first.corpus_id == second.corpus_id
    assert second.granted is False, (
        "a second grant to the same owner is a bug, not a stronger grant"
    )
    assert conn.execute("SELECT COUNT(*) AS n FROM corpus_grants").fetchone()["n"] == 1


# ---------------------------------------------------------------- chunks


def test_chunks_store_both_page_spaces_and_their_warning_scope(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
        " page_count, storage_path) VALUES ('d1', ?, 'c1', 'f.pdf', 'h1', 2, '/x')",
        (owner_id,),
    )
    conn.commit()

    store_chunks(
        conn,
        [
            Chunk(
                document_id="d1",
                corpus_id="c1",
                ordinal=0,
                page=PageRef(index=0, label="vii"),
                text="preface text",
                warnings=("low_confidence_ocr",),
            ),
            Chunk(
                document_id="d1",
                corpus_id="c1",
                ordinal=1,
                page=PageRef(index=1, label="1"),
                text="body text",
            ),
        ],
    )

    loaded = load_chunks(conn, "d1")
    assert [c.page.index for c in loaded] == [0, 1]
    assert [c.page.label for c in loaded] == ["vii", "1"]
    assert loaded[0].warnings == ("low_confidence_ocr",)

    # 2A.5, answered by running the parser: LightningParse 0.4.1 emits no warnings array
    # at all, so "none" is a measured fact rather than the hedge it was in 2A.
    assert all(c.warning_scope == "none" for c in loaded)

    summary = warning_summary(conn, "d1")
    assert summary["chunks"] == 2
    assert summary["with_warnings"] == 1
    assert summary["scope_none"] == 2
