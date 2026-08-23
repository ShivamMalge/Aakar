"""A deterministic fake provider.

Used to record cassettes in tests without a network call, and as the standing example of
what a real backend must implement. The live Gemini-class backend arrives in Phase 2,
which is the first phase allowed to make a model call at all.
"""

from __future__ import annotations

import hashlib

from .base import ChatRequest, ChatResponse, EmbedRequest, EmbedResponse, Usage, VlmRequest


class StubProvider:
    def __init__(self, *, dim: int = 8, usd_per_call: float = 0.001) -> None:
        self._dim = dim
        self._usd = usd_per_call

    def chat(self, req: ChatRequest) -> ChatResponse:
        return ChatResponse(
            text=f"stub-chat:{hashlib.sha256(req.prompt.encode()).hexdigest()[:12]}",
            usage=Usage(prompt_tokens=len(req.prompt.split()), completion_tokens=4, usd=self._usd),
        )

    def vlm(self, req: VlmRequest) -> ChatResponse:
        digest = hashlib.sha256(
            req.prompt.encode() + b"".join(hashlib.sha256(i).digest() for i in req.images)
        ).hexdigest()[:12]
        return ChatResponse(
            text=f"stub-vlm:{digest}",
            usage=Usage(prompt_tokens=len(req.prompt.split()), completion_tokens=4, usd=self._usd),
        )

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        vectors = []
        for text in req.texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append(tuple(digest[i] / 255.0 for i in range(self._dim)))
        return EmbedResponse(
            vectors=tuple(vectors),
            usage=Usage(prompt_tokens=sum(len(t.split()) for t in req.texts), usd=self._usd),
        )
