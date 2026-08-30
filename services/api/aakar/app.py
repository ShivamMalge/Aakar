"""FastAPI application (Phase 0 scaffold).

Only auth exists so far. Ingestion, retrieval, generation and the critic arrive in
Phases 2 and 3 — Phase 0 is explicitly out of scope for all of them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

import structlog
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from aakar.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    authenticate,
    issue_session,
    read_session,
)
from aakar.config import Settings
from aakar.db import init_db, new_id
from aakar.ingest import (
    IngestRejected,
    check_file,
    check_quota,
    content_hash,
    enqueue,
    get_job_for_owner,
    resolve_corpus,
)

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


class UploadAccepted(BaseModel):
    """202, not 200. The work has not happened yet (D-034)."""

    job_id: str
    document_id: str
    corpus_id: str
    page_count: int
    #: False when an identical file was already ingested — no parse, no embedding cost.
    corpus_created: bool


class JobStatus(BaseModel):
    job_id: str
    status: str
    pages_done: int
    pages_total: int
    failure_reason: str | None = None


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

    @app.post("/ingest/upload", status_code=status.HTTP_202_ACCEPTED)
    async def upload(
        owner_id: Annotated[str, Depends(require_owner)],
        settings: Annotated[Settings, Depends(get_settings)],
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        file: Annotated[UploadFile, File()],
    ) -> UploadAccepted:
        """Boundary checks synchronously; the work asynchronously (D-034).

        Every refusal happens here, before the response: size, page count, OCR page count,
        encryption, the per-owner daily quota and the global queue bound. A student who
        uploads something unacceptable finds out now, not seventeen minutes later.

        Returns **202 Accepted** with a job id. It is not 200, because nothing has been
        parsed yet and a 200 would say otherwise.
        """
        data = await file.read()

        try:
            facts = check_file(data)
            check_quota(conn, owner_id, facts.page_count)
        except IngestRejected as rejected:
            # 422, not 400: the request was well-formed, its content was not acceptable.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": str(rejected.code),
                    "message": rejected.message,
                    "remedy": rejected.remedy,
                },
            ) from rejected

        resolution = resolve_corpus(conn, owner_id, data, file.filename or "upload.pdf")

        storage = settings.db_path.parent / "uploads"
        storage.mkdir(parents=True, exist_ok=True)
        document_id = new_id("doc")
        path = storage / f"{document_id}.pdf"
        path.write_bytes(data)

        conn.execute(
            "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash,"
            " page_count, storage_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                owner_id,
                resolution.corpus_id,
                file.filename or "upload.pdf",
                content_hash(data),
                facts.page_count,
                str(path),
            ),
        )
        # The page map is stored, not recomputed later (2A.6): a re-derivation that
        # disagreed with the one the limits were checked against would be a silent
        # inconsistency between the citation space and the addressing space.
        conn.executemany(
            "INSERT OR REPLACE INTO document_pages (document_id, page_index, page_label)"
            " VALUES (?, ?, ?)",
            [(document_id, i, label) for i, label in enumerate(facts.page_labels)],
        )
        conn.commit()

        try:
            job_id = enqueue(conn, document_id, owner_id, facts.page_count)
        except IngestRejected as rejected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": str(rejected.code),
                    "message": rejected.message,
                    "remedy": rejected.remedy,
                },
            ) from rejected

        log.info("ingest.queued", job=job_id, owner_id=owner_id, pages=facts.page_count)
        return UploadAccepted(
            job_id=job_id,
            document_id=document_id,
            corpus_id=resolution.corpus_id,
            page_count=facts.page_count,
            corpus_created=resolution.created,
        )

    @app.get("/ingest/jobs/{job_id}")
    def job_status(
        job_id: str,
        owner_id: Annotated[str, Depends(require_owner)],
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    ) -> JobStatus:
        """Owner-scoped, and 404 for another owner's job — a 403 would confirm it exists."""
        job = get_job_for_owner(conn, job_id, owner_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such job")
        return JobStatus(
            job_id=job.id,
            status=job.status,
            pages_done=job.pages_done,
            pages_total=job.pages_total,
            failure_reason=job.failure_reason,
        )

    return app


app = create_app()
