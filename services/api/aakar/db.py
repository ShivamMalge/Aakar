"""SQLite bookkeeping (task 0.5). Schema lives in schema.sql; this module only opens
connections and applies it."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Every table is in exactly one of these categories, and each category has its own
# invariant. The registry test asserts both — that the partition is total, and that each
# table satisfies its category — so a new table cannot be added without someone deciding
# which access rule governs it.
#
# D-029 moved `corpora` out of the owner-scoped set: it is content-addressed and ownerless,
# and access to it runs through `corpus_grants`.

#: owner_id NOT NULL. The owner is the resource's holder (D-011).
OWNER_SCOPED_TABLES = (
    "documents",
    "topics",
    "spec_versions",
    "approvals",
    "llm_calls",
    "qa_cache_meta",
)

#: No owner column at all. Reachable only through a grant (D-029). `chunks` belongs to
#: the corpus it was parsed from, so it inherits the corpus's sharing exactly.
CONTENT_ADDRESSED_TABLES = ("corpora", "chunks")

#: The grant itself: held by exactly one of an owner or a group (ruling e).
GRANT_TABLES = ("corpus_grants",)

#: Principals, not resources. They describe *who* can hold a grant.
IDENTITY_TABLES = ("users", "groups", "group_members")

#: Bookkeeping that belongs to the database rather than to anyone.
META_TABLES = ("schema_meta",)

ALL_CATEGORIES = {
    "owner_scoped": OWNER_SCOPED_TABLES,
    "content_addressed": CONTENT_ADDRESSED_TABLES,
    "grant": GRANT_TABLES,
    "identity": IDENTITY_TABLES,
    "meta": META_TABLES,
}

SCHEMA_VERSION = 2


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    """0 when the database predates `schema_meta`, which is how a v1 file identifies itself."""
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["value"]) if row is not None else 0


def _corpora_is_v1(conn: sqlite3.Connection) -> bool:
    """A v1 `corpora` carries owner_id; a v2 one carries content_hash."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(corpora)")}
    return bool(columns) and "owner_id" in columns


def _stamp_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Reshape a v1 database in place. Returns what it did; empty means nothing to do.

    Runs BEFORE `apply_schema`, not after. `apply_schema` is `CREATE TABLE IF NOT EXISTS`
    throughout, so it cannot reshape a table that already exists — and worse, its
    `idx_corpora_hash` index would fail against a v1 `corpora` that has no `content_hash`.
    So this creates the two tables it touches itself, and `apply_schema` then fills in
    everything else and no-ops over these.

    Only one migration exists: v1 -> v2, moving `corpora` from owned to content-addressed
    (D-029). Every v1 corpus becomes a content-addressed row plus a grant to its former
    owner, so nobody loses access and nothing is deleted.
    """
    if not _corpora_is_v1(conn):
        return []

    steps: list[str] = []
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE corpora RENAME TO corpora_v1")
    steps.append("renamed corpora -> corpora_v1")

    # Created here rather than left to apply_schema, because the copy below needs them.
    conn.executescript(
        """
        CREATE TABLE corpora (
            id           TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS corpus_grants (
            id         TEXT PRIMARY KEY,
            corpus_id  TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
            owner_id   TEXT REFERENCES users(id) ON DELETE CASCADE,
            group_id   TEXT REFERENCES groups(id) ON DELETE CASCADE,
            granted_at TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK ((owner_id IS NOT NULL) + (group_id IS NOT NULL) = 1)
        );
        """
    )

    # A v1 corpus had no content hash. Borrow the hash of a document that belongs to it;
    # a corpus with no documents falls back to its own id, which is unique by definition
    # and keeps the row addressable rather than dropping it.
    cursor = conn.execute(
        """
        INSERT INTO corpora (id, content_hash, name, created_at)
        SELECT c.id,
               COALESCE((SELECT d.content_hash FROM documents d
                         WHERE d.corpus_id = c.id ORDER BY d.created_at LIMIT 1),
                        'migrated:' || c.id),
               c.name,
               c.created_at
        FROM corpora_v1 c
        """
    )
    steps.append(f"copied {cursor.rowcount} corpora rows")

    cursor = conn.execute(
        """
        INSERT INTO corpus_grants (id, corpus_id, owner_id, group_id, granted_at)
        SELECT 'grant_' || c.id, c.id, c.owner_id, NULL, c.created_at
        FROM corpora_v1 c
        """
    )
    steps.append(f"granted {cursor.rowcount} corpora to their former owners")

    conn.execute("DROP TABLE corpora_v1")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    steps.append("dropped corpora_v1")
    return steps


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    apply_schema(conn)
    _stamp_version(conn)
    return conn


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()
