"""Task 0.7 — owner session (D-011). Two principals, and only two."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aakar.app import create_app, get_settings
from aakar.auth import (
    SESSION_COOKIE,
    authenticate,
    ensure_owner,
    issue_session,
    read_session,
)
from aakar.config import Settings

from .conftest import OWNER_EMAIL, OWNER_PASSWORD

SECRET = "unit-test-secret-at-least-32-bytes-long"


def test_ensure_owner_is_idempotent(conn: sqlite3.Connection) -> None:
    first = ensure_owner(conn, OWNER_EMAIL, OWNER_PASSWORD)
    second = ensure_owner(conn, OWNER_EMAIL, OWNER_PASSWORD)
    assert first == second
    assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1


def test_password_is_not_stored_in_the_clear(conn: sqlite3.Connection, owner_id: str) -> None:
    stored = conn.execute("SELECT password_hash FROM users WHERE id = ?", (owner_id,)).fetchone()[
        "password_hash"
    ]
    assert OWNER_PASSWORD not in stored
    assert stored.startswith("$argon2")


def test_authenticate_accepts_and_rejects(conn: sqlite3.Connection, owner_id: str) -> None:
    assert authenticate(conn, OWNER_EMAIL, OWNER_PASSWORD) == owner_id
    assert authenticate(conn, OWNER_EMAIL, "wrong") is None
    assert authenticate(conn, "nobody@example.com", OWNER_PASSWORD) is None


def test_session_round_trip() -> None:
    token = issue_session("usr_1", SECRET)
    assert read_session(token, SECRET) == "usr_1"


def test_session_signed_with_another_secret_is_rejected() -> None:
    token = issue_session("usr_1", SECRET)
    assert read_session(token, "a-different-secret-also-32-bytes-long-x") is None


def test_expired_session_is_rejected() -> None:
    stale = issue_session("usr_1", SECRET, now=datetime.now(UTC) - timedelta(days=30))
    assert read_session(stale, SECRET) is None


def test_garbage_token_is_rejected() -> None:
    assert read_session("not-a-jwt", SECRET) is None


@pytest.fixture
def client(db_path: Path, owner_id: str) -> TestClient:
    settings = Settings.from_env()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{**settings.__dict__, "db_path": db_path, "auth_secret": SECRET}
    )
    return TestClient(app)


def test_me_requires_a_session(client: TestClient) -> None:
    """The whole of G-05 rests on this returning 401 rather than data."""
    assert client.get("/auth/me").status_code == 401


def test_login_then_me(client: TestClient, owner_id: str) -> None:
    login = client.post("/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert login.status_code == 200
    assert login.json()["owner_id"] == owner_id
    assert SESSION_COOKIE in login.cookies

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {"owner_id": owner_id, "role": "owner"}


def test_login_with_bad_password_is_401(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"email": OWNER_EMAIL, "password": "nope"})
    assert resp.status_code == 401
    assert SESSION_COOKIE not in resp.cookies


def test_forged_cookie_does_not_authenticate(client: TestClient) -> None:
    forged = issue_session("usr_attacker", "attacker-secret-also-32-bytes-long-xx")
    client.cookies.set(SESSION_COOKIE, forged)
    assert client.get("/auth/me").status_code == 401


def test_logout_clears_the_session(client: TestClient) -> None:
    client.post("/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert client.get("/auth/me").status_code == 200
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_short_auth_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 7518 §3.2 — an HS256 key under 32 bytes weakens the MAC. Fail loudly at boot."""
    monkeypatch.setenv("AAKAR_AUTH_SECRET", "too-short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings.from_env()
