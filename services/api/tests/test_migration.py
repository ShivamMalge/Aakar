"""2A.2 — the v1 to v2 migration (D-029).

`corpora` was owned; it is now content-addressed and ownerless, with access through
`corpus_grants`. An existing database has to survive that, and nobody may lose access on
the way through — a migration that silently drops a row is worse than one that fails.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aakar.auth import ensure_owner
from aakar.db import SCHEMA_VERSION, connect, init_db, migrate, schema_version

# The v1 shape, verbatim, so this test does not drift with the current schema.sql.
V1_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE corpora (
    id         TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE documents (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    corpus_id    TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    page_count   INTEGER,
    storage_path TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '1');
"""


def _v1_database(path: Path) -> tuple[str, str]:
    """A v1 database with two owners, each holding their own corpus."""
    conn = connect(path)
    conn.executescript(V1_SCHEMA)
    owner_a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    owner_b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('ca', ?, 'A book')", (owner_a,))
    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('cb', ?, 'B book')", (owner_b,))
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('da', ?, 'ca', 'a.pdf', 'hash_a', '/data/a.pdf')",
        (owner_a,),
    )
    conn.commit()
    conn.close()
    return owner_a, owner_b


def test_a_v1_database_reports_version_one(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    _v1_database(path)
    conn = connect(path)
    assert schema_version(conn) == 1
    conn.close()


def test_migration_makes_corpora_content_addressed(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    _v1_database(path)

    conn = init_db(path)  # applies schema.sql, then migrates
    columns = {row[1] for row in conn.execute("PRAGMA table_info(corpora)")}

    assert "owner_id" not in columns, "corpora kept its owner column"
    assert "content_hash" in columns
    assert schema_version(conn) == SCHEMA_VERSION
    conn.close()


def test_nobody_loses_access(tmp_path: Path) -> None:
    """Every v1 corpus becomes a grant to its former owner. That is the whole obligation."""
    path = tmp_path / "v1.db"
    owner_a, owner_b = _v1_database(path)

    conn = init_db(path)
    grants = {
        (row["owner_id"], row["corpus_id"])
        for row in conn.execute("SELECT owner_id, corpus_id FROM corpus_grants")
    }
    assert grants == {(owner_a, "ca"), (owner_b, "cb")}

    # And the corpora themselves survived, with their names intact.
    names = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM corpora")}
    assert names == {"ca": "A book", "cb": "B book"}
    conn.close()


def test_a_corpus_inherits_its_document_hash(tmp_path: Path) -> None:
    """A v1 corpus had no hash. Borrowing one from its document is what makes it
    addressable, and is what lets a future identical upload dedupe onto it."""
    path = tmp_path / "v1.db"
    _v1_database(path)

    conn = init_db(path)
    hashes = {
        row["id"]: row["content_hash"]
        for row in conn.execute("SELECT id, content_hash FROM corpora")
    }

    assert hashes["ca"] == "hash_a", "should have taken the hash of its own document"
    # 'cb' has no documents, so it falls back to something unique rather than being dropped.
    assert hashes["cb"].startswith("migrated:")
    assert len(set(hashes.values())) == 2, "migrated hashes must stay unique"
    conn.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """`init_db` runs on every connection, so it must be safe to run repeatedly."""
    path = tmp_path / "v1.db"
    _v1_database(path)

    first = init_db(path)
    grants_before = first.execute("SELECT COUNT(*) AS n FROM corpus_grants").fetchone()["n"]
    first.close()

    second = init_db(path)
    assert (
        second.execute("SELECT COUNT(*) AS n FROM corpus_grants").fetchone()["n"] == grants_before
    )
    assert schema_version(second) == SCHEMA_VERSION
    second.close()

    third = init_db(path)
    assert migrate(third) == [], "a migrated database should report no further steps"
    third.close()


def test_a_fresh_database_needs_no_migration(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "fresh.db")
    assert schema_version(conn) == SCHEMA_VERSION
    assert migrate(conn) == []
    conn.close()


def test_the_migrated_database_still_enforces_its_constraints(tmp_path: Path) -> None:
    """A migration that leaves the constraints off would be worse than not migrating."""
    import pytest

    path = tmp_path / "v1.db"
    _v1_database(path)
    conn = init_db(path)

    with pytest.raises(sqlite3.IntegrityError):  # duplicate content hash
        conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('x', 'hash_a', 'dup')")
    with pytest.raises(sqlite3.IntegrityError):  # grant held by nobody
        conn.execute("INSERT INTO corpus_grants (id, corpus_id) VALUES ('gx', 'ca')")
    conn.close()
