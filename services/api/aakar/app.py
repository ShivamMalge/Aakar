"""FastAPI application (Phase 0 scaffold).

Only auth exists so far. Ingestion, retrieval, generation and the critic arrive in
Phases 2 and 3 — Phase 0 is explicitly out of scope for all of them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

import structlog
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel

from aakar.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    authenticate,
    issue_session,
    read_session,
)
from aakar.config import Settings
from aakar.db import init_db

log = structlog.get_logger()


def get_settings() -> Settings:
    return Settings.from_env()


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    conn = init_db(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def require_owner(
    settings: Annotated[Settings, Depends(get_settings)],
    aakar_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> str:
    """Gate for everything owner-private: uploads, chunks, draft specs, cached answers.

    Also gates draft renders (D-004) — `/render/{topic}?spec_version=` must not be
    reachable without it, or the Rule 8 approval gate could be walked around.
    """
    owner_id = read_session(aakar_session, settings.auth_secret) if aakar_session else None
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="owner session required",
        )
    return owner_id


class LoginBody(BaseModel):
    email: str
    password: str


class MeResponse(BaseModel):
    owner_id: str
    role: str = "owner"


def create_app() -> FastAPI:
    app = FastAPI(title="Aakar API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(
        body: LoginBody,
        response: Response,
        settings: Annotated[Settings, Depends(get_settings)],
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    ) -> MeResponse:
        owner_id = authenticate(conn, body.email, body.password)
        if owner_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
            )
        response.set_cookie(
            SESSION_COOKIE,
            issue_session(owner_id, settings.auth_secret),
            httponly=True,
            samesite="lax",
            max_age=int(SESSION_TTL.total_seconds()),
        )
        log.info("owner.login", owner_id=owner_id)
        return MeResponse(owner_id=owner_id)

    @app.post("/auth/logout")
    def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.get("/auth/me")
    def me(owner_id: Annotated[str, Depends(require_owner)]) -> MeResponse:
        return MeResponse(owner_id=owner_id)

    return app


app = create_app()
