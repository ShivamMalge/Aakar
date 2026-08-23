from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from aakar.auth import ensure_owner
from aakar.db import init_db

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "aakar.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = init_db(db_path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def owner_id(conn: sqlite3.Connection) -> str:
    return ensure_owner(conn, OWNER_EMAIL, OWNER_PASSWORD)
