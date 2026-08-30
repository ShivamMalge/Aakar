"""Environment configuration. Values come from env only — see .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aakar.providers.models import check_configured_models

REPO_ROOT = Path(__file__).resolve().parents[3]


# RFC 7518 §3.2: an HS256 key below 32 bytes weakens the MAC. PyJWT warns; we refuse.
MIN_AUTH_SECRET_BYTES = 32

DEV_AUTH_SECRET = "dev-only-insecure-secret-change-me-before-any-real-use"

# Verified live 2026-08-30 against ai.google.dev. `gemini-2.0-flash` was shut down on
# 2026-06-01 and `text-embedding-004` on 2026-01-14; both were pinned here (D-045).
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_VLM_MODEL = "gemini-3.6-flash"
DEFAULT_EMBED_MODEL = "gemini-embedding-001"


@dataclass(frozen=True)
class Settings:
    provider_mode: str
    model: str
    vlm_model: str
    embed_model: str
    api_key: str | None
    max_usd_per_run: float
    auth_secret: str
    owner_email: str
    owner_password: str | None
    db_path: Path
    cassette_dir: Path
    qdrant_url: str

    @staticmethod
    def from_env() -> Settings:
        mode = os.environ.get("AAKAR_PROVIDER_MODE", "replay")
        if mode not in {"live", "record", "replay"}:
            raise ValueError(f"AAKAR_PROVIDER_MODE must be live|record|replay, got {mode!r}")
        secret = os.environ.get("AAKAR_AUTH_SECRET", DEV_AUTH_SECRET)
        if len(secret.encode()) < MIN_AUTH_SECRET_BYTES:
            raise ValueError(
                f"AAKAR_AUTH_SECRET must be at least {MIN_AUTH_SECRET_BYTES} bytes "
                f"(RFC 7518 §3.2); got {len(secret.encode())}"
            )
        # Every model pin is checked here, at construction, in every mode (D-045).
        # `gemini-2.0-flash` and `text-embedding-004` were both pinned and both already
        # shut down; nothing noticed, because no test ever resolved a model name.
        model = os.environ.get("AAKAR_MODEL", DEFAULT_MODEL)
        vlm_model = os.environ.get("AAKAR_VLM_MODEL", DEFAULT_VLM_MODEL)
        embed_model = os.environ.get("AAKAR_EMBED_MODEL", DEFAULT_EMBED_MODEL)
        answer_model = os.environ.get("AAKAR_ANSWER_MODEL") or model
        check_configured_models(
            {
                "AAKAR_MODEL": model,
                "AAKAR_ANSWER_MODEL": answer_model,
                "AAKAR_VLM_MODEL": vlm_model,
                "AAKAR_EMBED_MODEL": embed_model,
            }
        )

        db = Path(os.environ.get("AAKAR_DB_PATH", REPO_ROOT / "data" / "aakar.db"))
        return Settings(
            provider_mode=mode,
            model=model,
            vlm_model=vlm_model,
            embed_model=embed_model,
            api_key=os.environ.get("AAKAR_API_KEY") or None,
            max_usd_per_run=float(os.environ.get("AAKAR_MAX_USD_PER_RUN", "1.00")),
            auth_secret=secret,
            owner_email=os.environ.get("AAKAR_OWNER_EMAIL", "owner@example.com"),
            owner_password=os.environ.get("AAKAR_OWNER_PASSWORD") or None,
            db_path=db,
            cassette_dir=Path(
                os.environ.get("AAKAR_CASSETTE_DIR", REPO_ROOT / "tests" / "cassettes")
            ),
            qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        )
