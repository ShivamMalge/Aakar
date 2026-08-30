"""Embeddings (2C.1). Model and dimensionality are fixed by D-043 — a one-way door.

Everything goes through the provider abstraction, so cost logging and the cassette apply
(Rule 7). The only thing that differs between replay and production is which vectors come
back, not which code path produces them.

**The replay embedder is dimension-matched on purpose.** A test collection built at the
stub's natural width would exercise a shape production never uses, and the first real
ingest would be the first time the real shape ran.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from aakar.providers import EmbedRequest, Provider

#: D-043. Changing either means re-embedding every corpus, and corpora are shared (D-029).
DEFAULT_MODEL = "text-embedding-004"
DEFAULT_DIMENSIONS = 768


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = DEFAULT_MODEL
    dimensions: int = DEFAULT_DIMENSIONS

    @staticmethod
    def from_env() -> EmbeddingConfig:
        return EmbeddingConfig(
            model=os.environ.get("AAKAR_EMBED_MODEL", DEFAULT_MODEL),
            dimensions=int(os.environ.get("AAKAR_EMBED_DIMENSIONS", DEFAULT_DIMENSIONS)),
        )


_TOKEN = re.compile(r"[a-z0-9]+")


def local_embed(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """A deterministic, dimension-matched embedder for replay.

    Hashed bag-of-words with sub-token character trigrams: lexical, not semantic. It is
    honest about what it is — enough to exercise the index, the scoping and the floor
    end-to-end without a key, and **not** enough to calibrate a similarity threshold
    against (D-041). Paraphrases sharing words land close; paraphrases sharing only meaning
    do not.
    """
    vector = [0.0] * dimensions
    tokens = _TOKEN.findall(text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
        # Trigrams give partial credit for morphology ("focus"/"focuses"), which a pure
        # word hash cannot express at all.
        for i in range(len(token) - 2):
            tri = hashlib.sha256(token[i : i + 3].encode()).digest()
            vector[int.from_bytes(tri[:4], "big") % dimensions] += 0.25

    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class Embedder:
    """Embeds through the provider when one is given; deterministically otherwise.

    `provider=None` is the replay path and is explicit rather than implicit: a caller that
    forgot to wire a provider gets vectors that obviously are not from a model, instead of
    silently cheap ones that look real.
    """

    def __init__(self, provider: Provider | None, config: EmbeddingConfig | None = None) -> None:
        self._provider = provider
        self.config = config or EmbeddingConfig.from_env()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._provider is None:
            return [local_embed(t, self.config.dimensions) for t in texts]

        response = self._provider.embed(EmbedRequest(model=self.config.model, texts=tuple(texts)))
        vectors = [list(v) for v in response.vectors]
        for vector in vectors:
            if len(vector) != self.config.dimensions:
                raise ValueError(
                    f"{self.config.model} returned {len(vector)} dimensions, but the "
                    f"collection is built for {self.config.dimensions} (D-043). Changing "
                    "dimensionality means re-embedding every corpus."
                )
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
