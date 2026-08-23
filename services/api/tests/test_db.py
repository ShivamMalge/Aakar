"""Task 0.5 — bookkeeping schema, and the owner_id invariant from D-011."""

from __future__ import annotations

import sqlite3

import pytest

from aakar.db import OWNER_SCOPED_TABLES

EXPECTED_TABLES = {
    "users",
    "corpora",
    "documents",
    "topics",
    "spec_versions",
    "approvals",
    "llm_calls",
    "qa_cache_meta",
    "schema_meta",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_all_expected_tables_exist(conn: sqlite3.Connection) -> None:
    found = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    assert found >= EXPECTED_TABLES


def test_every_user_scoped_table_carries_owner_id(conn: sqlite3.Connection) -> None:
    """D-011: owner_id from day one, so vNext multi-user is policy, not migration."""
    for table in OWNER_SCOPED_TABLES:
        assert "owner_id" in _columns(conn, table), f"{table} is missing owner_id"


def test_no_user_scoped_table_was_added_without_owner_id(conn: sqlite3.Connection) -> None:
    """Catches the drift the previous test cannot: a new table nobody registered."""
    exempt = {"users", "schema_meta"}
    found = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    for table in found - exempt:
        assert "owner_id" in _columns(conn, table), (
            f"{table} has no owner_id — add it, or add {table!r} to the exempt set with a reason"
        )
        assert table in OWNER_SCOPED_TABLES, (
            f"{table} is owner-scoped but not listed in OWNER_SCOPED_TABLES"
        )


def test_qa_cache_meta_requires_corpus_id(conn: sqlite3.Connection) -> None:
    """D-007: the cache scope key is (corpus_id, topic, part). NOT NULL keeps it structural."""
    info = {row[1]: row for row in conn.execute("PRAGMA table_info(qa_cache_meta)")}
    assert info["corpus_id"][3] == 1, "corpus_id must be NOT NULL"


def test_spec_version_status_is_constrained(conn: sqlite3.Connection, owner_id: str) -> None:
    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('c1', ?, 'x')", (owner_id,))
    conn.execute(
        "INSERT INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES ('t1', ?, 'c1', 'eye', 'Eye')",
        (owner_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO spec_versions (id, owner_id, topic_id, attempt, status, spec_json)"
            " VALUES ('s1', ?, 't1', 0, 'published', '{}')",
            (owner_id,),
        )


def test_foreign_keys_are_enforced(conn: sqlite3.Connection, owner_id: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO corpora (id, owner_id, name) VALUES ('c9', 'usr_nonexistent', 'x')"
        )
