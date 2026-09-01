"""Environment configuration (D-060).

## Three layers, and the order matters

1. **The process environment** — highest. Never overwritten.
2. **`.env` at the repository root** — loaded once, at first `Settings.from_env()`.
3. **The defaults in this module** — lowest.

Environment-wins is what makes this safe to ship. A container, a CI runner or a systemd unit
that exports `AAKAR_MODEL` keeps its value even if a stray `.env` is sitting in the image;
the reverse would let a file committed by accident silently override a deployment.

`.env` was not read at all until D-060, while `.env.example` opened with "copy to .env and
fill" — so the documented way to configure this project did not work, and a key placed
exactly where the template said to put it was invisible. That is the same class of trap as
`.env.example` shipping a stale relevance floor: a document that lies about the code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from aakar.providers.models import check_configured_models

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

_loaded = False


def load_env_file(path: Path | None = None, *, force: bool = False) -> bool:
    """Load `.env` into the process environment, without overriding what is already set.

    Idempotent by design: `Settings.from_env()` is called on several startup paths and from
    tests, and re-reading the file each time would let an edit take effect halfway through a
    running process — a source of the exact "it worked a minute ago" confusion that a config
    layer must not produce. `force` exists so a test can reload deliberately.

    Returns whether a file was read. A missing `.env` is the normal case in production and
    in CI, so it is not an error.
    """
    global _loaded  # noqa: PLW0603 - one process-wide load, deliberately
    if _loaded and not force:
        return False
    _loaded = True
    target = path or ENV_FILE
    if not target.is_file():
        return False
    # override=False is the whole ruling: the environment wins.
    load_dotenv(target, override=False)
    return True


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
        load_env_file()
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
