"""Owner session (D-011).

Aakar v1 has exactly two principals: the **owner** (one authenticated user; all uploads,
corpora, drafts and approvals belong to them) and the **anonymous share-link reader**
(one topic's approved spec and its cached summaries, nothing else).

The API owns the session because every protected resource lives behind FastAPI. Auth.js
was the alternative and was rejected: its v5 session token is a JWE rather than a plain
JWS, awkward to verify from Python, and it would put session authority in the stack that
holds none of the protected data.

Real multi-user auth is vNext. Nothing here assumes a single row in `users`, so that
change is a policy change rather than a migration.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from aakar.db import new_id

SESSION_COOKIE = "aakar_session"
SESSION_TTL = timedelta(days=14)
_ALGORITHM = "HS256"

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return str(_pwd.hash(password))


def verify_password(password: str, password_hash: str) -> bool:
    return bool(_pwd.verify(password, password_hash))


def ensure_owner(conn: sqlite3.Connection, email: str, password: str) -> str:
    """Create the owner row if absent; return its id. Idempotent."""
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is not None:
        return str(row["id"])
    owner_id = new_id("usr")
    conn.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
        (owner_id, email, hash_password(password)),
    )
    conn.commit()
    return owner_id


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> str | None:
    row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        # Hash anyway so a missing account and a wrong password cost the same time.
        _pwd.hash(password)
        return None
    if not verify_password(password, str(row["password_hash"])):
        return None
    return str(row["id"])


def issue_session(owner_id: str, secret: str, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": owner_id,
        "role": "owner",
        "iat": int(issued.timestamp()),
        "exp": int((issued + SESSION_TTL).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def read_session(token: str, secret: str) -> str | None:
    """Return the owner id, or None if the token is absent, expired or forged."""
    try:
        claims: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if claims.get("role") != "owner":
        return None
    sub = claims.get("sub")
    return str(sub) if isinstance(sub, str) else None
