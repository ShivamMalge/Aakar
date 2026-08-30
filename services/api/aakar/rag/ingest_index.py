"""Wiring the index into ingest (2C.1).

Kept apart from `worker.py` so the worker has no Qdrant import: a machine running the
worker without a reachable index should fail on *indexing*, with a message that says so,
rather than on import.
"""

from __future__ import annotations

from collections.abc import Callable

from qdrant_client import QdrantClient

from aakar.ingest.chunks import Chunk

from .embedding import Embedder
from .index import ensure_collection, upsert_chunks


def make_indexer(qdrant: QdrantClient, embedder: Embedder) -> Callable[[list[Chunk]], int]:
    """A callable the worker can hold without knowing what Qdrant is.

    `ensure_collection` runs once here rather than per batch: it verifies the collection's
    shape against D-043, and doing that on every upsert would turn a one-way-door check
    into per-chunk overhead.
    """
    ensure_collection(qdrant, embedder.config)

    def index(chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        vectors = embedder.embed([chunk.text for chunk in chunks])
        return upsert_chunks(qdrant, chunks, vectors)

    return index
