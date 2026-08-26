"""Content-addressed corpus resolution (2A.2, D-029).

The whole of the sharing model is here, and it is four lines of SQL. Two owners who upload
byte-identical files land on one `corpora` row, one parse and one embedding cost; two
owners with different files cannot, because the hash differs and there is no code path
that relates non-identical content.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from aakar.db import new_id


def content_hash(data: bytes) -> str:
    """SHA-256 of the raw bytes. The dedupe key, and the whole isolation argument.

    Deliberately over the bytes as uploaded, not over extracted text: two visually similar
    PDFs are different documents with different page maps, and merging them would merge
    their citations too.
    """
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CorpusResolution:
    corpus_id: str
    #: False when an identical file was already ingested — no parse, no embedding cost.
    created: bool
    #: False when this owner already held a grant, i.e. they uploaded the same file twice.
    granted: bool


def resolve_corpus(
    conn: sqlite3.Connection, owner_id: str, data: bytes, name: str
) -> CorpusResolution:
    """Find or create the corpus for these bytes, and make sure this owner can reach it.

    Idempotent in both halves: re-uploading the same file neither duplicates the corpus nor
    duplicates the grant, which is what the unique indexes enforce underneath.
    """
    digest = content_hash(data)

    row = conn.execute("SELECT id FROM corpora WHERE content_hash = ?", (digest,)).fetchone()
    if row is None:
        corpus_id = new_id("cor")
        conn.execute(
            "INSERT INTO corpora (id, content_hash, name) VALUES (?, ?, ?)",
            (corpus_id, digest, name),
        )
        created = True
    else:
        corpus_id = str(row["id"])
        created = False

    held = conn.execute(
        "SELECT 1 FROM corpus_grants WHERE corpus_id = ? AND owner_id = ?",
        (corpus_id, owner_id),
    ).fetchone()
    if held is None:
        conn.execute(
            "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES (?, ?, ?)",
            (new_id("grant"), corpus_id, owner_id),
        )
        granted = True
    else:
        granted = False

    conn.commit()
    return CorpusResolution(corpus_id=corpus_id, created=created, granted=granted)


def can_read(conn: sqlite3.Connection, owner_id: str, corpus_id: str) -> bool:
    """Access is by grant, never by ownership (D-029).

    Includes group grants: a member of a group holding the grant can read it. No route
    calls this yet — the group half is schema shape only (ruling e) — but the check is
    written once, here, rather than reimplemented at each future call site.
    """
    row = conn.execute(
        """
        SELECT 1 FROM corpus_grants g
        LEFT JOIN group_members m ON m.group_id = g.group_id
        WHERE g.corpus_id = ? AND (g.owner_id = ? OR m.user_id = ?)
        LIMIT 1
        """,
        (corpus_id, owner_id, owner_id),
    ).fetchone()
    return row is not None
