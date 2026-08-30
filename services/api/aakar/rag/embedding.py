"""Embeddings (2C.1). Model and dimensionality are fixed by D-043 — a one-way door.

Everything goes through the provider abstraction, so cost logging and the cassette apply
(Rule 7). The only thing that differs between replay and production is which vectors come
back, not which code path produces them.

**The replay embedder is dimension-matched on purpose.** A test collection built at the
stub's natural width would exercise a shape production never uses, and the first real
ingest would be the first time the real shape ran. That principle is exactly what the
D-043 correction shows was not applied far enough: the *model* was never resolved either,
so the first real call would have been the first 404.

## Normalization — the MRL trap

`gemini-embedding-001` returns **unnormalized** vectors at any `output_dimensionality`
other than its native 3072. The provider docs are explicit that the caller must L2
normalize, and that only the 3072 default (and `gemini-embedding-2`) are normalized for
you.

This matters more than it sounds. Cosine similarity on unnormalized vectors still returns
a number between -1 and 1; it is simply the *wrong* number, weighted by magnitude. Nothing
raises. Retrieval quietly gets worse, the relevance floor starts refusing covered
questions, and every symptom points at "the embedder is weak" rather than "we skipped a
division".

So `_l2_normalize` is applied to **every** vector, from every source, unconditionally.
Normalizing an already-unit vector is a no-op, so there is no branch on model or width to
get wrong later — and a future model that changes its normalization behaviour cannot
silently break this.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from aakar.providers import EmbedRequest, Provider

#: D-043 (amended). Changing either means re-embedding every corpus, and corpora are
#: shared (D-029).
DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 768

#: The provider embeds documents and queries asymmetrically; using one task type for both
#: throws that away. Indexing uses the first, searching the second.
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"


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


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """Unit-length a vector. A no-op on one that is already unit length.

    Applied unconditionally rather than behind a model check — see the module docstring.
    An unnormalized vector does not fail, it just degrades, which is the hardest kind of
    defect to attribute.
    """
    norm = math.sqrt(sum(x * x for x in vector))
    return list(vector) if norm == 0.0 else [x / norm for x in vector]


_TOKEN = re.compile(r"[a-z0-9]+")


def local_embed(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """A deterministic, dimension-matched embedder for replay.

    Hashed bag-of-words with sub-token character trigrams: lexical, not semantic. Honest
    about what it is — enough to exercise the index, the scoping and the floor end-to-end
    without a key, and **not** enough to calibrate a similarity threshold against (D-041).
    """
    vector = [0.0] * dimensions
    for token in _TOKEN.findall(text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
        # Trigrams give partial credit for morphology ("focus"/"focuses"), which a pure
        # word hash cannot express at all.
        for i in range(len(token) - 2):
            tri = hashlib.sha256(token[i : i + 3].encode()).digest()
            vector[int.from_bytes(tri[:4], "big") % dimensions] += 0.25
    return l2_normalize(vector)


class Embedder:
    """Embeds through the provider when one is given; deterministically otherwise.

    `provider=None` is the replay path and is explicit rather than implicit: a caller that
    forgot to wire a provider gets vectors that obviously are not from a model, instead of
    silently cheap ones that look real.
    """

    def __init__(self, provider: Provider | None, config: EmbeddingConfig | None = None) -> None:
        self._provider = provider
        self.config = config or EmbeddingConfig.from_env()

    def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        if self._provider is None:
            return [local_embed(t, self.config.dimensions) for t in texts]

        response = self._provider.embed(
            EmbedRequest(
                model=self.config.model,
                texts=tuple(texts),
                output_dimensionality=self.config.dimensions,
                task_type=task_type,
            )
        )
        vectors = [list(v) for v in response.vectors]
        for vector in vectors:
            if len(vector) != self.config.dimensions:
                raise ValueError(
                    f"{self.config.model} returned {len(vector)} dimensions, but the "
                    f"collection is built for {self.config.dimensions} (D-043). Changing "
                    "dimensionality means re-embedding every corpus."
                )
        # Unconditional: gemini-embedding-001 does NOT normalize below 3072 dimensions.
        return [l2_normalize(v) for v in vectors]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed chunks for indexing."""
        return self._embed(texts, TASK_DOCUMENT)

    def embed_query(self, text: str) -> list[float]:
        """Embed a question. Deliberately a different task type from `embed`."""
        return self._embed([text], TASK_QUERY)[0]

    def embed_one(self, text: str) -> list[float]:
        """Kept for callers that mean a query. Alias of `embed_query`."""
        return self.embed_query(text)
