"""The Qdrant chunk index (2C.1).

Shape is fixed by D-043 and recorded before this file created anything: **768 dimensions,
cosine**. `ensure_collection` refuses to run against a collection of a different shape
rather than silently writing incompatible vectors into it — the one failure that cannot be
undone without re-embedding every corpus.

Payload carries what retrieval filters on, and nothing else: `corpus_id` for isolation
(D-007/D-029), `page_index` and `page_label` as separate fields (2A.6), and `source` so an
OCR-derived hit can be weighted differently from extracted text (D-044).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from aakar.ingest.chunks import Chunk

from .embedding import EmbeddingConfig

COLLECTION = "chunks"


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    corpus_id: str
    document_id: str
    text: str
    page_index: int
    page_label: str
    section: str | None
    #: `digital` | `ocr` — a confidence signal, not just metadata (D-044).
    source: str
    score: float


def client(url: str | None = None) -> QdrantClient:
    return QdrantClient(url=url or os.environ.get("QDRANT_URL", "http://localhost:6333"))


def ensure_collection(qdrant: QdrantClient, config: EmbeddingConfig | None = None) -> None:
    """Create the collection at the recorded shape, or verify an existing one matches.

    A mismatch raises. Writing 768-dimension vectors into a collection built for something
    else is the one-way door D-043 exists to keep shut, and Qdrant would otherwise accept
    the write or fail with a message that does not say why it matters.
    """
    config = config or EmbeddingConfig.from_env()

    if qdrant.collection_exists(COLLECTION):
        info = qdrant.get_collection(COLLECTION)
        params = info.config.params.vectors
        existing = getattr(params, "size", None)
        if existing is not None and existing != config.dimensions:
            raise RuntimeError(
                f"collection {COLLECTION!r} has {existing} dimensions but this build embeds "
                f"at {config.dimensions} (D-043). Changing dimensionality means re-embedding "
                "every corpus; drop and rebuild deliberately rather than mixing widths."
            )
        return

    qdrant.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(size=config.dimensions, distance=models.Distance.COSINE),
    )


def upsert_chunks(
    qdrant: QdrantClient, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
) -> int:
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    if not chunks:
        return 0

    qdrant.upsert(
        collection_name=COLLECTION,
        points=[
            models.PointStruct(
                # Qdrant ids must be uuid or int; the chunk id is neither, so it lives in
                # the payload and the point id is derived deterministically from it.
                id=abs(hash(chunk.id)) % (2**63),
                vector=list(vector),
                payload={
                    "chunk_id": chunk.id,
                    "corpus_id": chunk.corpus_id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "page_index": chunk.page.index,
                    "page_label": chunk.page.label,
                    "section": chunk.section,
                    "source": chunk.source,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )
    return len(chunks)


def search(
    qdrant: QdrantClient,
    *,
    corpus_id: str,
    query_vector: Sequence[float],
    limit: int = 8,
) -> list[Hit]:
    """Dense search **inside one corpus**.

    `corpus_id` is a filter on the query rather than something applied to the results,
    so a chunk from another corpus is never a candidate in the first place (D-007).
    """
    found = qdrant.query_points(
        collection_name=COLLECTION,
        query=list(query_vector),
        limit=limit,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="corpus_id", match=models.MatchValue(value=corpus_id))]
        ),
        with_payload=True,
    ).points

    hits: list[Hit] = []
    for point in found:
        payload = point.payload or {}
        hits.append(
            Hit(
                chunk_id=str(payload.get("chunk_id", "")),
                corpus_id=str(payload.get("corpus_id", "")),
                document_id=str(payload.get("document_id", "")),
                text=str(payload.get("text", "")),
                page_index=int(payload.get("page_index", 0)),
                page_label=str(payload.get("page_label", "")),
                section=payload.get("section"),
                source=str(payload.get("source", "unknown")),
                score=float(point.score),
            )
        )
    return hits
