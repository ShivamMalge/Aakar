"""LightningParse adapter (2A.5, answered).

Spec §3 pins LightningParse. It **is** available: PyPI `lightningparse`, pinned at 0.4.1.
My Phase 2A report said otherwise and was wrong — `importlib.find_spec` only sees installed
packages, and I drew a conclusion about PyPI from that plus one failed download command.

## What 0.4.1 emits — measured, and corrected twice

My first answer said "there is no warnings array". **That was wrong**, for a reason worth
recording: ``metadata.warnings`` is an *optional* key, present only when the parser has
something to report. Every document I had measured was clean, so I read absence-in-this-
output as absence-from-the-schema. It appears the moment a page has a problem::

    Page 1: content stream uses unsupported filter 'JBIG2Decode', falling back to OCR

I also reported that a text-layer-free PDF "produces zero blocks", implying no OCR path.
**Also wrong**: I had tested with genuinely blank pages, which correctly yield nothing. A
real scan OCRs fine — see ``tier`` and ``source`` below.

The signals, and their granularity:

==========================  =============  ============================================
signal                      granularity    observed
==========================  =============  ============================================
``metadata.warnings``       per DOCUMENT   flat list of strings, each naming its page
``metadata.tier``           per DOCUMENT   ``digital`` | ``scanned`` | ``mixed``
``block.source``            per BLOCK      ``digital`` | ``ocr``
``block.section_id``        per BLOCK      ``header``, …
==========================  =============  ============================================

**The answer the amendment asked for: warnings are PER-DOCUMENT.** They name a page in
their text, but they are a flat list of strings rather than structured per-page data, so
attributing one to a chunk would mean parsing prose — a provenance claim the parser never
made. They are stored at document level, and ``chunks.warning_scope`` records ``document``
when the document carries any, so the UI can say what a warning actually covers.

``block.source`` remains the finest per-chunk signal, and it distinguishes ``digital`` from
``ocr`` text — exactly the provenance-strength input 2A.5 wanted.

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
    #: `metadata.warnings` — a per-DOCUMENT array. Present only when something went wrong,
    #: which is why an earlier reading of a clean document concluded it did not exist.
    #: Each entry names its page by convention ("Page 1: ..."), but it is a flat list of
    #: strings, not structured per-page data, so it is stored at document level.
    warnings: tuple[str, ...] = ()


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
        warnings=tuple(str(w) for w in (metadata.get("warnings") or [])),
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
                # Warnings are per-DOCUMENT (see ParsedDocument.warnings), so a chunk
                # records the SCOPE rather than copying a document-wide string onto one
                # paragraph — which would be a provenance claim the parser never made.
                warnings=(),
                warning_scope="document" if parsed.warnings else "none",
            )
        )
    return chunks
