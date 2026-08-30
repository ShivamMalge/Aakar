"""Chunk storage, and the parser warnings that ride with it (2A.5, 2A.6).

## 2A.5, answered

**Answered, by running it.** LightningParse 0.4.1 emits **no warnings array at all**. What
it does emit is ``block.source`` (per BLOCK — finer than per chunk) and ``metadata.tier``
(per document). So ``source`` is stored per chunk at block granularity, which is the finest
available, and ``warning_scope`` defaults to ``"none"`` as a measured fact rather than a
hedge. See ``parser.py`` for the full measurement.

``warnings_json`` and ``warning_scope`` are kept for the day the parser gains a warnings
array: the cost is one string per chunk, and the cost of the alternative is a UI that
attributes a document-wide signal to one paragraph — a provenance claim, exactly the class
of error D-030 exists to stop.

The instruction not to modify LightningParse from this repository is respected: `parser.py`
calls it and translates its errors, and nothing reimplements it.

## Page label and page index

Every chunk carries both (2A.6). See `pages.py` for why neither may be inferred from the
other.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from aakar.db import new_id

from .pages import PageRef

#: Whether a warnings array describes one chunk or the document it came from.
WarningScope = Literal["block", "chunk", "document", "none", "unknown"]


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of a document.

    `page` is a `PageRef`, not an int, so a caller cannot pass an index where a label was
    meant. That mistake is invisible until a citation renders, and by then it looks like a
    content error rather than a units error.
    """

    document_id: str
    corpus_id: str
    ordinal: int
    page: PageRef
    text: str
    section: str | None = None
    #: LightningParse `block.source` — per BLOCK, the finest granularity it offers.
    source: str = "unknown"
    warnings: tuple[str, ...] = ()
    #: 0.4.1 emits no warnings array, so "none" is a MEASURED default rather than the
    #: hedge it was in 2A. A parser that gains one must say what a value describes.
    warning_scope: WarningScope = "none"
    id: str = field(default_factory=lambda: new_id("chunk"))


def store_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> int:
    """Persist chunks, warnings and both page spaces. Returns the number written."""
    conn.executemany(
        """
        INSERT INTO chunks
            (id, corpus_id, document_id, ordinal, page_index, page_label, section,
             text, source, warnings_json, warning_scope)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                chunk.id,
                chunk.corpus_id,
                chunk.document_id,
                chunk.ordinal,
                chunk.page.index,
                chunk.page.label,
                chunk.section,
                chunk.text,
                chunk.source,
                json.dumps(list(chunk.warnings)),
                chunk.warning_scope,
            )
            for chunk in chunks
        ],
    )
    conn.commit()
    return len(chunks)


def load_chunks(conn: sqlite3.Connection, document_id: str) -> list[Chunk]:
    rows = conn.execute(
        """
        SELECT id, corpus_id, document_id, ordinal, page_index, page_label, section,
               text, source, warnings_json, warning_scope
        FROM chunks WHERE document_id = ? ORDER BY ordinal
        """,
        (document_id,),
    ).fetchall()

    return [
        Chunk(
            id=str(row["id"]),
            corpus_id=str(row["corpus_id"]),
            document_id=str(row["document_id"]),
            ordinal=int(row["ordinal"]),
            page=PageRef(index=int(row["page_index"]), label=str(row["page_label"])),
            section=row["section"],
            text=str(row["text"]),
            source=str(row["source"]),
            warnings=tuple(json.loads(row["warnings_json"])),
            warning_scope=row["warning_scope"],
        )
        for row in rows
    ]


def warning_summary(conn: sqlite3.Connection, document_id: str) -> dict[str, int]:
    """How many chunks carry warnings, and at what scope.

    The scope is reported alongside the count because "12 chunks have warnings" means two
    very different things depending on whether those warnings were attributed per chunk or
    copied from the document.
    """
    summary = {"chunks": 0, "with_warnings": 0}
    summary.update({f"scope_{s}": 0 for s in ("block", "chunk", "document", "none", "unknown")})
    summary.update({f"source_{s}": 0 for s in ("digital", "ocr", "mixed", "unknown")})

    for chunk in load_chunks(conn, document_id):
        summary["chunks"] += 1
        if chunk.warnings:
            summary["with_warnings"] += 1
        summary[f"scope_{chunk.warning_scope}"] += 1
        key = f"source_{chunk.source}"
        summary[key] = summary.get(key, 0) + 1
    return summary
