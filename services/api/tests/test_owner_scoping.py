"""Item 6 — owner scoping: a column is not enforcement.

D-011 puts `owner_id` on seven tables so vNext multi-user is a policy change rather than
a migration. Two different things need proving:

1. The column is NOT NULL on exactly those seven tables, so an eighth user-scoped table
   added without it fails loudly instead of silently becoming global.
2. Owner A cannot reach owner B's data through any route.

The second one has nothing to bite on yet — see `test_no_route_serves_an_owner_scoped_resource`.
That is stated as a tripwire rather than skipped, so the first owner-scoped route added
cannot land without an isolation test.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from aakar.app import create_app
from aakar.db import OWNER_SCOPED_TABLES

# Tables that are deliberately global. Everything else must be owner-scoped.
GLOBAL_TABLES = {"users", "schema_meta"}

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


def test_owner_id_is_not_null_on_exactly_the_seven_scoped_tables(
    conn: sqlite3.Connection,
) -> None:
    """Nullable owner_id is a row that belongs to nobody, which is a row everybody can read."""
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
    assert len(OWNER_SCOPED_TABLES) == 7


def test_an_eighth_scoped_table_cannot_be_added_without_owner_id(
    conn: sqlite3.Connection,
) -> None:
    """The tripwire D-011 needs: every non-global table is owner-scoped and NOT NULL."""
    for table in sorted(_tables(conn) - GLOBAL_TABLES):
        column = _column(conn, table, "owner_id")
        assert column is not None, (
            f"{table!r} has no owner_id. Add one, or add it to GLOBAL_TABLES with a reason."
        )
        assert column[3] == 1, f"{table!r}.owner_id is nullable; D-011 requires NOT NULL"
        assert table in OWNER_SCOPED_TABLES, (
            f"{table!r} is owner-scoped but missing from OWNER_SCOPED_TABLES"
        )


def test_owner_id_foreign_keys_are_enforced(conn: sqlite3.Connection, owner_id: str) -> None:
    """A NOT NULL column holding an id nobody owns would scope nothing."""
    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('c1', ?, 'x')", (owner_id,))
    try:
        conn.execute(
            "INSERT INTO corpora (id, owner_id, name) VALUES ('c2', 'usr_does_not_exist', 'y')"
        )
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover - only reached if FK enforcement regresses
        raise AssertionError("corpora.owner_id accepted an id with no matching user")


def test_two_owners_rows_do_not_leak_across_a_scoped_query(conn: sqlite3.Connection) -> None:
    """Storage-level check, standing in for the route-level one that has no routes yet.

    This proves the *data* is separable by owner_id. It does not prove any handler
    applies the filter — no handler exists. See the next test.
    """
    from aakar.auth import ensure_owner

    owner_a = ensure_owner(conn, "a@example.com", "password-a-long-enough")
    owner_b = ensure_owner(conn, "b@example.com", "password-b-long-enough")
    assert owner_a != owner_b

    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('ca', ?, 'A')", (owner_a,))
    conn.execute("INSERT INTO corpora (id, owner_id, name) VALUES ('cb', ?, 'B')", (owner_b,))
    conn.commit()

    seen_by_a = {
        row["id"] for row in conn.execute("SELECT id FROM corpora WHERE owner_id = ?", (owner_a,))
    }
    assert seen_by_a == {"ca"}, "an owner-scoped query returned another owner's rows"


def test_no_route_serves_an_owner_scoped_resource() -> None:
    """The tripwire for the cross-owner isolation tests that cannot be written yet.

    Every route today is either unauthenticated (`/healthz`, the docs) or returns only
    the caller's own session (`/auth/*`). None of them take a resource id, so there is no
    route on which owner A could request owner B's row — and therefore nothing to assert
    a 404 against. Ingestion, specs and cached answers all arrive in Phase 2.

    When the first owner-scoped route lands this test fails, and whoever adds it has to
    add the cross-owner 404 assertions alongside it rather than after.
    """
    app = create_app()
    # starlette types routes as BaseRoute, which has no `path`; every concrete route
    # class in use here does, so read it the same way the methods are read.
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
        "If a new route serves an owner-scoped resource, add cross-owner isolation tests "
        "asserting 404 (not 403) for another owner's id, then update KNOWN_ROUTES."
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
    # cross-owner read here to exploit — recorded so a future change to row lookup is
    # a visible change in behaviour.
    assert response.json()["owner_id"] == "usr_someone_else"
