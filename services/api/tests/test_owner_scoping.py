"""Access control: who can reach which rows.

Restated for D-029. Phase 0 asked "does every user-scoped table carry owner_id"; that is
no longer the whole question, because `corpora` is content-addressed and ownerless and
access to it runs through `corpus_grants`.

The assertion is now: **owner A cannot read a corpus they hold no grant for.**

Every table is placed in exactly one category in `aakar/db.py`, each with its own
invariant, and the partition is asserted to be total — so a new table cannot be added
without someone deciding which access rule governs it.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from aakar.app import create_app
from aakar.db import (
    ALL_CATEGORIES,
    CONTENT_ADDRESSED_TABLES,
    OWNER_SCOPED_TABLES,
)

# Routes that exist today and serve nothing owner-private. FastAPI's own docs endpoints
# are included because they are part of the surface even though we did not write them.
KNOWN_ROUTES = {
    ("GET", "/healthz"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }


def _column(conn: sqlite3.Connection, table: str, column: str) -> tuple[object, ...] | None:
    for row in conn.execute(f"PRAGMA table_info({table})"):
        if row[1] == column:
            return tuple(row)
    return None


# --------------------------------------------------------------- the partition


def test_every_table_is_in_exactly_one_category(conn: sqlite3.Connection) -> None:
    """The tripwire D-011 needed, restated for D-029.

    Adding a table forces a decision about which access rule governs it, rather than
    defaulting to owner-scoped or to nothing at all.
    """
    registered: dict[str, str] = {}
    for category, tables in ALL_CATEGORIES.items():
        for table in tables:
            assert table not in registered, f"{table} is in two categories"
            registered[table] = category

    found = _tables(conn)
    unregistered = sorted(found - set(registered))
    assert not unregistered, (
        f"tables in no category: {unregistered}. Add each to one of "
        f"{sorted(ALL_CATEGORIES)} in aakar/db.py, with a reason."
    )
    missing = sorted(set(registered) - found)
    assert not missing, f"registered but absent from the schema: {missing}"


def test_owner_id_is_not_null_on_exactly_the_owner_scoped_tables(
    conn: sqlite3.Connection,
) -> None:
    """Nullable owner_id is a row belonging to nobody, which is a row everybody can read.

    `corpus_grants` is deliberately excluded: its owner_id IS nullable, because a grant may
    be held by a group instead (ruling e). Its invariant is the XOR check, asserted below.
    """
    with_notnull_owner = {
        table
        for table in _tables(conn)
        if (col := _column(conn, table, "owner_id")) is not None and col[3] == 1
    }
    assert with_notnull_owner == set(OWNER_SCOPED_TABLES), (
        "owner_id NOT NULL does not match OWNER_SCOPED_TABLES.\n"
        f"  in schema but not registered: {sorted(with_notnull_owner - set(OWNER_SCOPED_TABLES))}\n"
        f"  registered but not enforced : {sorted(set(OWNER_SCOPED_TABLES) - with_notnull_owner)}"
    )
    assert len(OWNER_SCOPED_TABLES) == 6


def test_a_registered_owner_scoped_table_really_is_scoped(conn: sqlite3.Connection) -> None:
    """Registration alone proves nothing; the column has to be present and NOT NULL."""
    for table in sorted(OWNER_SCOPED_TABLES):
        column = _column(conn, table, "owner_id")
        assert column is not None, f"{table!r} is registered owner-scoped but has no owner_id"
        assert column[3] == 1, f"{table!r}.owner_id is nullable; D-011 requires NOT NULL"


def test_a_content_addressed_table_has_no_owner(conn: sqlite3.Connection) -> None:
    """D-029: `corpora` must not regrow an owner column, or dedupe breaks again."""
    for table in CONTENT_ADDRESSED_TABLES:
        assert _column(conn, table, "owner_id") is None, (
            f"{table} has an owner_id. Content-hash dedupe requires shared rows, which is "
            "why access moved to corpus_grants (D-029)."
        )
        #  is keyed by content_hash;  inherits its corpus's sharing.
        assert (
            _column(conn, table, "content_hash") is not None
            or _column(conn, table, "corpus_id") is not None
        )


# ------------------------------------------------------------------- grants


def test_a_grant_is_held_by_exactly_one_principal(conn: sqlite3.Connection, owner_id: str) -> None:
    """Ruling (e): owner XOR group. Unrepresentable, not merely discouraged."""
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'hash1', 'x')")
    conn.execute("INSERT INTO groups (id, name, created_by) VALUES ('g1', 'Class', ?)", (owner_id,))
    conn.commit()

    conn.execute(
        "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES ('gr1', 'c1', ?)", (owner_id,)
    )
    conn.execute("INSERT INTO corpus_grants (id, corpus_id, group_id) VALUES ('gr2', 'c1', 'g1')")

    with pytest.raises(sqlite3.IntegrityError):  # granted to nobody
        conn.execute("INSERT INTO corpus_grants (id, corpus_id) VALUES ('gr3', 'c1')")
    with pytest.raises(sqlite3.IntegrityError):  # granted to both
        conn.execute(
            "INSERT INTO corpus_grants (id, corpus_id, owner_id, group_id)"
            " VALUES ('gr4', 'c1', ?, 'g1')",
            (owner_id,),
        )


def test_access_is_by_grant_not_by_ownership(conn: sqlite3.Connection) -> None:
    """The Phase 0 owner-scoping assertion, restated for D-029.

    It is no longer "owner A cannot read owner B's corpus" — corpora have no owner. It is
    **owner A cannot read a corpus they hold no grant for.**
    """
    from aakar.auth import ensure_owner

    owner_a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    owner_b = ensure_owner(conn, "b@example.com", "password-b-long-enough")

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('shared', 'h1', 'S')")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('b_only', 'h2', 'B')")
    for grant_id, corpus, owner in (
        ("g1", "shared", owner_a),
        ("g2", "shared", owner_b),
        ("g3", "b_only", owner_b),
    ):
        conn.execute(
            "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES (?, ?, ?)",
            (grant_id, corpus, owner),
        )
    conn.commit()

    def readable(owner: str) -> set[str]:
        return {
            row["corpus_id"]
            for row in conn.execute(
                "SELECT corpus_id FROM corpus_grants WHERE owner_id = ?", (owner,)
            )
        }

    assert readable(owner_a) == {"shared"}
    assert readable(owner_b) == {"shared", "b_only"}
    # Both hold a grant on the same corpus. That is dedupe working, not a leak: they
    # uploaded byte-identical files.
    assert "shared" in readable(owner_a) & readable(owner_b)


def test_a_group_grant_reaches_its_members(conn: sqlite3.Connection, owner_id: str) -> None:
    """No routes read this yet (ruling e is schema shape only), but the query it will use
    has to be expressible, or the shape is not actually usable."""
    from aakar.auth import ensure_owner

    student = ensure_owner(conn, "student@example.com", "password-student-long-enough")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'Class set')")
    conn.execute(
        "INSERT INTO groups (id, name, created_by) VALUES ('g1', 'Biology', ?)", (owner_id,)
    )
    conn.execute("INSERT INTO group_members (group_id, user_id) VALUES ('g1', ?)", (student,))
    conn.execute("INSERT INTO corpus_grants (id, corpus_id, group_id) VALUES ('gr1', 'c1', 'g1')")
    conn.commit()

    reachable = {
        row["corpus_id"]
        for row in conn.execute(
            """
            SELECT g.corpus_id FROM corpus_grants g
            LEFT JOIN group_members m ON m.group_id = g.group_id
            WHERE g.owner_id = ? OR m.user_id = ?
            """,
            (student, student),
        )
    }
    assert reachable == {"c1"}

    # The group's creator is not a member, so they do not reach it through this grant.
    not_a_member = {
        row["corpus_id"]
        for row in conn.execute(
            """
            SELECT g.corpus_id FROM corpus_grants g
            LEFT JOIN group_members m ON m.group_id = g.group_id
            WHERE g.owner_id = ? OR m.user_id = ?
            """,
            (owner_id, owner_id),
        )
    }
    assert not_a_member == set()


def test_owner_id_foreign_keys_are_enforced(conn: sqlite3.Connection, owner_id: str) -> None:
    """A NOT NULL column holding an id nobody owns would scope nothing."""
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'x')")
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('d1', ?, 'c1', 'f.pdf', 'h1', '/tmp/f.pdf')",
        (owner_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
            " storage_path) VALUES ('d2', 'usr_does_not_exist', 'c1', 'f.pdf', 'h2', '/x')"
        )


def test_two_owners_rows_do_not_leak_across_a_scoped_query(conn: sqlite3.Connection) -> None:
    """Storage-level check on an owner-scoped table.

    Uses `documents` now that `corpora` is content-addressed — and note that both
    documents legitimately point at the same corpus.
    """
    from aakar.auth import ensure_owner

    owner_a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    owner_b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    assert owner_a != owner_b

    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'shared')")
    for doc, owner in (("da", owner_a), ("db", owner_b)):
        conn.execute(
            "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
            " storage_path) VALUES (?, ?, 'c1', 'f.pdf', 'h1', '/tmp/f.pdf')",
            (doc, owner),
        )
    conn.commit()

    seen_by_a = {
        row["id"] for row in conn.execute("SELECT id FROM documents WHERE owner_id = ?", (owner_a,))
    }
    assert seen_by_a == {"da"}, "an owner-scoped query returned another owner's rows"


# ------------------------------------------------------------------- routes


def test_no_route_serves_an_owner_scoped_resource() -> None:
    """The tripwire for the cross-owner isolation tests that cannot be written yet.

    Every route today is either unauthenticated (`/healthz`, the docs) or returns only the
    caller's own session (`/auth/*`). None takes a resource id, so there is no route on
    which owner A could request owner B's row. Upload lands later in 2A.

    When the first grant-scoped route lands this test fails, and whoever adds it has to
    add the cross-owner 404 assertions alongside it rather than after.
    """
    app = create_app()
    found = {
        (method, str(getattr(route, "path", "")))
        for route in app.routes
        for method in sorted(getattr(route, "methods", set()) or set())
        if method not in {"HEAD", "OPTIONS"}
    }
    assert found == KNOWN_ROUTES, (
        "the route surface changed.\n"
        f"  new routes: {sorted(found - KNOWN_ROUTES)}\n"
        f"  removed   : {sorted(KNOWN_ROUTES - found)}\n"
        "If a new route serves a grant-scoped resource, add isolation tests asserting 404 "
        "(not 403) for a corpus the caller holds no grant for, then update KNOWN_ROUTES."
    )


def test_auth_me_returns_only_the_calling_owner(conn: sqlite3.Connection, owner_id: str) -> None:
    """The one route that touches owner identity: it must echo the caller, never a lookup."""
    from aakar.app import get_settings
    from aakar.auth import SESSION_COOKIE, issue_session
    from aakar.config import Settings

    secret = "owner-scoping-secret-at-least-32-bytes"
    settings = Settings.from_env()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{**settings.__dict__, "auth_secret": secret}
    )
    client = TestClient(app)

    client.cookies.set(SESSION_COOKIE, issue_session("usr_someone_else", secret))
    response = client.get("/auth/me")

    assert response.status_code == 200
    # It reflects the session subject rather than reading a row, so there is no
    # cross-owner read here to exploit.
    assert response.json()["owner_id"] == "usr_someone_else"
