"""SQLite bookkeeping (task 0.5). Schema lives in schema.sql; this module only opens
connections and applies it."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Every table that carries owner_id (D-011). The Phase 0 gate asserts this list against
# the live schema, so adding a user-scoped table without owner_id fails the test.
OWNER_SCOPED_TABLES = (
    "corpora",
    "documents",
    "topics",
    "spec_versions",
    "approvals",
    "llm_calls",
    "qa_cache_meta",
)


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


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    apply_schema(conn)
    return conn


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()
