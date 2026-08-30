"""One interface for chat, VLM and embeddings (spec Rule 7).

Every call in the project goes through a Provider so that cost logging (D8) and the
record/replay cassette are impossible to bypass. Nothing else in the codebase may talk
to a model API directly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system: str
    prompt: str
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass(frozen=True)
class VlmRequest:
    model: str
    system: str
    prompt: str
    # Screenshot bytes are hashed into the cassette key (D8) — a different render must
    # not replay a critique written about a different image.
    images: tuple[bytes, ...] = ()
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass(frozen=True)
class EmbedRequest:
    model: str
    texts: tuple[str, ...]
    #: Matryoshka (MRL) truncation. `gemini-embedding-001` defaults to 3072 and accepts
    #: 128-3072; we ask for 768 (D-043).
    output_dimensionality: int | None = None
    #: `RETRIEVAL_DOCUMENT` when indexing, `RETRIEVAL_QUERY` when searching. The provider
    #: embeds the two asymmetrically, and using one for both loses that.
    task_type: str | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0


@dataclass(frozen=True)
class ChatResponse:
    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class EmbedResponse:
    vectors: tuple[tuple[float, ...], ...]
    usage: Usage = field(default_factory=Usage)


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def request_hash(kind: str, req: ChatRequest | VlmRequest | EmbedRequest) -> str:
    """hash(canonical_request) -> cassette key (D8).

    Image bytes are hashed rather than embedded so the key stays small and stable, and
    so a re-render that produces byte-identical PNGs replays cleanly.
    """
    if isinstance(req, ChatRequest):
        payload: dict[str, object] = {
            "model": req.model,
            "system": req.system,
            "prompt": req.prompt,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
    elif isinstance(req, VlmRequest):
        payload = {
            "model": req.model,
            "system": req.system,
            "prompt": req.prompt,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "images": [hashlib.sha256(b).hexdigest() for b in req.images],
        }
    else:
        # Both extra fields change the returned vectors, so both belong in the cassette
        # key. A recording made at 3072 must not replay for a request asking for 768.
        payload = {
            "model": req.model,
            "texts": list(req.texts),
            "output_dimensionality": req.output_dimensionality,
            "task_type": req.task_type,
        }

    return hashlib.sha256(f"{kind}:{_canonical(payload)}".encode()).hexdigest()


@runtime_checkable
class Provider(Protocol):
    """Implemented by the live backend and by the stub used in tests."""

    def chat(self, req: ChatRequest) -> ChatResponse: ...

    def vlm(self, req: VlmRequest) -> ChatResponse: ...

    def embed(self, req: EmbedRequest) -> EmbedResponse: ...


class BudgetExceeded(RuntimeError):
    """Raised when a run would exceed AAKAR_MAX_USD_PER_RUN (D8)."""
