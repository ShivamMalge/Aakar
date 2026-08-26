"""Chunk storage, and the parser warnings that ride with it (2A.5, 2A.6).

## What is NOT here, and why

**LightningParse is not available in this environment.** It is not installed, and it is not
on PyPI — spec §3 describes it as Shivam's own library. Chunking, page-numbered text
extraction and the warnings array all belong to it.

So this module does not parse anything. It defines the shape those results land in, and it
is explicit about the one thing 2A.5 asked to be reported:

> **Whether LightningParse's warnings are per-chunk or per-document is UNKNOWN here,
> because the library could not be run.**

Rather than guess, `warning_scope` is stored per row, and `Chunk.warning_scope` defaults to
``"unknown"`` for anything this repository writes without having seen the parser. When
LightningParse is wired in, whoever does it sets the scope truthfully and the column stops
being a question. The cost of that column is one string per chunk; the cost of assuming
per-chunk resolution that does not exist is a UI that attributes a document-wide warning to
one paragraph, which is a provenance claim — exactly the class of error D-030 exists to
stop.

The instruction not to modify LightningParse from this repository is respected: nothing
here imports it, wraps it, or reimplements it.

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
WarningScope = Literal["chunk", "document", "unknown"]


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
    warnings: tuple[str, ...] = ()
    #: Defaults to "unknown" on purpose — see the module docstring. A writer that knows
    #: better must say so; a writer that does not must not claim resolution it lacks.
    warning_scope: WarningScope = "unknown"
    id: str = field(default_factory=lambda: new_id("chunk"))


def store_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> int:
    """Persist chunks, warnings and both page spaces. Returns the number written."""
    conn.executemany(
        """
        INSERT INTO chunks
            (id, corpus_id, document_id, ordinal, page_index, page_label, section,
             text, warnings_json, warning_scope)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
               text, warnings_json, warning_scope
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
    summary = {"chunks": 0, "with_warnings": 0, "scope_chunk": 0, "scope_document": 0}
    summary["scope_unknown"] = 0

    for chunk in load_chunks(conn, document_id):
        summary["chunks"] += 1
        if chunk.warnings:
            summary["with_warnings"] += 1
        summary[f"scope_{chunk.warning_scope}"] += 1
    return summary
