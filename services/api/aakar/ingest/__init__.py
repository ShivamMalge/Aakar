"""Ingest boundary (Phase 2A).

`limits` refuses work before it starts; `pages` keeps the label and index spaces apart;
`corpus` does content-addressed dedupe and grants.

**LightningParse is not present in this environment** — it is not installed and not on
PyPI, being Shivam's own library (spec §3). Chunking, page-numbered text extraction and
the per-chunk warnings array (2A.5) all belong to it and are therefore not implemented
here. `chunks.py` defines the storage shape those warnings will land in and records what
is not yet known; it does not fake a parser.
"""

from .corpus import CorpusResolution, can_read, content_hash, resolve_corpus
from .limits import (
    DEFAULTS,
    IngestLimits,
    IngestRejected,
    PdfFacts,
    RejectionCode,
    check_file,
    check_quota,
    inspect_pdf,
)
from .pages import PageMap, PageRef

__all__ = [
    "DEFAULTS",
    "CorpusResolution",
    "IngestLimits",
    "IngestRejected",
    "PageMap",
    "PageRef",
    "PdfFacts",
    "RejectionCode",
    "check_file",
    "can_read",
    "check_quota",
    "content_hash",
    "resolve_corpus",
    "inspect_pdf",
]
