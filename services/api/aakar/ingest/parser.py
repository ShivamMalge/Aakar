"""LightningParse adapter (2A.5, answered).

Spec §3 pins LightningParse. It **is** available: PyPI `lightningparse`, pinned at 0.4.1.
My Phase 2A report said otherwise and was wrong — `importlib.find_spec` only sees installed
packages, and I drew a conclusion about PyPI from that plus one failed download command.

## What 0.4.1 actually emits — measured, not assumed

The amendment asked to capture "the warnings array" and report whether it is per-chunk or
per-document. **There is no warnings array in 0.4.1.** The output is::

    {"metadata": {"tier", "page_count", "parse_time_ms"},
     "pages": [{"page_num", "blocks": [{"type","text","spans","bbox","section_id","source"}]}]}

The quality signals that do exist, and their granularity:

==========================  =============  ==============================
signal                      granularity    observed values
==========================  =============  ==============================
``metadata.tier``           per DOCUMENT   ``digital`` | ``scanned``
``block.source``            per BLOCK      ``digital``
``block.section_id``        per BLOCK      ``header``, …
==========================  =============  ==============================

So the finest available granularity is **per block, which is finer than per chunk** — a
chunk is built from one or more blocks. ``source`` is therefore stored per chunk, and a
chunk assembled from blocks with differing sources would be marked ``mixed`` rather than
being given one of them arbitrarily.

``warnings_json`` and ``warning_scope`` are kept for the day the parser gains a warnings
array; ``warning_scope`` now defaults to ``none``, which is a measured fact about 0.4.1
rather than the hedge it was in 2A.

One further measured behaviour, useful at the boundary: **a PDF with no text layer reports
``tier: "scanned"`` and produces zero blocks.** LightningParse says so itself, cheaply.

This module does not modify LightningParse, and nothing here reimplements it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import lightningparse

from .chunks import Chunk
from .limits import IngestRejected, RejectionCode
from .pages import PageMap


@dataclass(frozen=True)
class ParsedDocument:
    """One parse, kept as structure rather than as a blob of text."""

    tier: str
    page_count: int
    parse_time_ms: int
    #: (page_index, section_id, source, text) per block, in reading order.
    blocks: tuple[tuple[int, str | None, str, str], ...]


def parse(path: Path) -> ParsedDocument:
    """Run LightningParse, translating its errors into ingest rejections.

    Its exception types are the parser's own vocabulary; the boundary speaks
    ``RejectionCode``, so every refusal — whoever raised it — reaches the uploader with a
    remedy attached.
    """
    try:
        raw = lightningparse.parse_pdf(str(path))
    except lightningparse.CorruptPdfError as exc:
        raise IngestRejected(
            RejectionCode.UNPARSEABLE,
            f"this PDF is damaged and could not be read: {exc}",
            remedy="Re-export or repair the PDF, then upload again.",
        ) from exc
    except lightningparse.UnsupportedPdfError as exc:
        raise IngestRejected(
            RejectionCode.UNPARSEABLE,
            f"this PDF uses a feature the parser does not support: {exc}",
            remedy="Re-save it as a standard PDF, then upload again.",
        ) from exc
    except lightningparse.OcrMissingDependencyError as exc:
        # A deployment problem, not the uploader's fault — so the remedy is addressed to
        # whoever runs the service, and the document is never silently accepted as empty.
        raise IngestRejected(
            RejectionCode.UNPARSEABLE,
            f"this document needs OCR, which is not available on this server: {exc}",
            remedy="Upload a version with selectable text, or ask for OCR to be enabled.",
        ) from exc
    except (lightningparse.OcrFailedError, lightningparse.OcrEngineError) as exc:
        raise IngestRejected(
            RejectionCode.UNPARSEABLE,
            f"OCR could not read this document: {exc}",
            remedy="Upload a clearer scan, or a version with selectable text.",
        ) from exc

    document = json.loads(raw)
    metadata = document.get("metadata", {})
    blocks: list[tuple[int, str | None, str, str]] = []

    for page in document.get("pages", []):
        # LightningParse numbers pages from 1; the index space is 0-based (2A.6).
        page_index = int(page.get("page_num", 1)) - 1
        for block in page.get("blocks", []):
            text = str(block.get("text", "")).strip()
            if not text:
                continue
            blocks.append(
                (
                    page_index,
                    block.get("section_id"),
                    str(block.get("source", "unknown")),
                    text,
                )
            )

    return ParsedDocument(
        tier=str(metadata.get("tier", "unknown")),
        page_count=int(metadata.get("page_count", 0)),
        parse_time_ms=int(metadata.get("parse_time_ms", 0)),
        blocks=tuple(blocks),
    )


def to_chunks(
    parsed: ParsedDocument,
    page_map: PageMap,
    *,
    document_id: str,
    corpus_id: str,
) -> list[Chunk]:
    """One chunk per block, carrying both page spaces and the block's own ``source``.

    Block-per-chunk is deliberate for now: blocks already carry ``section_id``, so they are
    heading-aware, and merging them would coarsen the ``source`` signal 2A.5 exists to
    preserve. Whether to merge short adjacent blocks is a retrieval-quality question for
    2B, and it should be settled against measured hit rates rather than guessed at here.
    """
    chunks: list[Chunk] = []
    for ordinal, (page_index, section, source, text) in enumerate(parsed.blocks):
        chunks.append(
            Chunk(
                document_id=document_id,
                corpus_id=corpus_id,
                ordinal=ordinal,
                page=page_map.ref(page_index),
                text=text,
                section=section,
                source=source,
                warnings=(),  # measured: 0.4.1 emits no warnings array at all
                warning_scope="none",
            )
        )
    return chunks
