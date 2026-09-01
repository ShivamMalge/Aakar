"""Phase 2C: retrieval, the floor, /ask ordering, citations, provenance resolution.

Runs against a **real Qdrant** when one is reachable, and skips otherwise — a fake index
would prove the test harness works, not that the collection shape and the filter do.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator

import pytest
from qdrant_client.models import VectorParams

from aakar.auth import ensure_owner
from aakar.ingest.chunks import Chunk, store_chunks
from aakar.ingest.pages import PageRef
from aakar.providers import CostLedger
from aakar.rag import (
    COLLECTION,
    DEFAULT_DIMENSIONS,
    Embedder,
    EmbeddingConfig,
    NotPermitted,
    ask,
    combine_sources,
    ensure_collection,
    local_embed,
    part_scope_terms,
    resolve_provenance,
    retrieve,
    upsert_chunks,
)
from aakar.rag.ask import Answer
from aakar.rag.index import Hit, client
from aakar.rag.quota import OwnerQuota, QuotaExceeded

qdrant_client = pytest.importorskip("qdrant_client")


def _qdrant_available() -> bool:
    try:
        client().get_collections()
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False
    return True


needs_qdrant = pytest.mark.skipif(
    not _qdrant_available(), reason="no Qdrant reachable; run `make up`"
)

CHAPTER = [
    (
        "The lens is a transparent biconvex structure that focuses light onto the retina.",
        "12",
        "digital",
    ),
    (
        "The cornea is the clear front layer of the eye and does most of the refraction.",
        "12",
        "digital",
    ),
    ("The retina contains rods and cones, the photoreceptor cells.", "13", "digital"),
    (
        "The iris controls the size of the pupil and so the amount of light entering.",
        "13",
        "digital",
    ),
    ("Aqueous humour fills the anterior chamber between cornea and lens.", "14", "ocr"),
]


@pytest.fixture
def indexed(conn: sqlite3.Connection) -> Iterator[tuple[str, Embedder]]:
    """A real corpus in a real collection, torn down afterwards."""
    owner = ensure_owner(conn, "reader@example.com", "password-reader-long-enough")
    conn.execute("INSERT INTO corpora (id, content_hash, name) VALUES ('c1', 'h1', 'Eye ch.1')")
    conn.execute(
        "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES ('g1', 'c1', ?)", (owner,)
    )
    conn.execute(
        "INSERT INTO documents (id, owner_id, corpus_id, filename, content_hash, storage_path)"
        " VALUES ('d1', ?, 'c1', 'eye.pdf', 'h1', '/x')",
        (owner,),
    )
    conn.execute(
        "INSERT INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES ('t1', ?, 'c1', 'human_eye', 'The Human Eye')",
        (owner,),
    )
    conn.commit()

    chunks = [
        Chunk(
            document_id="d1",
            corpus_id="c1",
            ordinal=i,
            # Index 0-based, label from the book. They diverge here on purpose (2A.6).
            page=PageRef(index=i, label=label),
            text=text,
            source=source,
        )
        for i, (text, label, source) in enumerate(CHAPTER)
    ]
    store_chunks(conn, chunks)

    embedder = Embedder(None, EmbeddingConfig(model="replay-local", dimensions=DEFAULT_DIMENSIONS))
    qdrant = client()
    ensure_collection(qdrant, embedder.config)
    upsert_chunks(qdrant, chunks, embedder.embed([c.text for c in chunks]))

    yield owner, embedder

    # Clear this corpus's POINTS, not the collection. Production never drops the
    # collection, and dropping it here left its data directory behind under the Windows
    # bind mount, so the next create_collection failed with "data already exists".
    from qdrant_client import models

    qdrant.delete(
        collection_name=COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="corpus_id", match=models.MatchValue(value="c1"))]
            )
        ),
    )


@pytest.fixture
def lexical_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the floor for tests whose subject is not the floor.

    D-050 raised `DEFAULT_FLOOR` to 0.45. Against this five-sentence fixture, embedded by
    the *lexical* replay embedder, a directly-covered question ("what does the lens do",
    with a chunk that opens "The lens is...") scores about 0.43 — so at the shipped default
    this corpus admits nothing at all, and three tests about the `/ask` ordering would start
    failing for a reason that has nothing to do with what they test.

    That is a fact about a toy corpus scored by word overlap, not a defect in the floor. It
    is also the cost the architect's ruling accepts: a false "not in your chapter" is a
    worse experience and a true statement, while false coverage is a confident wrong answer.

    The shipped default is still exercised, in two places that can carry the meaning:
    `test_an_uncovered_question_falls_below_the_floor` here, and the golden-set sweep in
    `test_evals.py`, which asserts the default both admits real questions and refuses every
    hard negative. Neither is skipped by this fixture (agents.md R1, R2).
    """
    monkeypatch.setenv("AAKAR_RELEVANCE_FLOOR", "0.35")


# ----------------------------------------------------------- scope and index


def test_the_scope_key_prefers_instance_of(conn: sqlite3.Connection) -> None:
    """D-022: parts sharing an instance_of are ONE retrieval target."""
    a = part_scope_terms("Mitochondrion", ["mitochondria"], "Mitochondrion")
    b = part_scope_terms("Mitochondrion", ["mitochondria"], "Mitochondrion")
    assert a == b
    # Without instance_of the part's own name heads the scope.
    assert part_scope_terms("Lens", ["crystalline lens"])[0] == "Lens"
    # Duplicates collapse, so a repeated alias does not weight the query twice.
    assert part_scope_terms("Lens", ["lens", "LENS"]) == ["Lens"]


def test_the_local_embedder_matches_the_recorded_dimensionality() -> None:
    """D-043 is a one-way door, and replay must exercise the production shape."""
    assert len(local_embed("the lens focuses light")) == DEFAULT_DIMENSIONS
    assert DEFAULT_DIMENSIONS == 768


@needs_qdrant
def test_the_collection_is_created_at_the_recorded_shape(indexed: tuple[str, Embedder]) -> None:
    info = client().get_collection(COLLECTION)
    params = info.config.params.vectors
    # A named-vector collection would return a dict here. This one is unnamed by design —
    # one vector per chunk — so the union is narrowed rather than indexed into.
    assert isinstance(params, VectorParams)
    assert params.size == DEFAULT_DIMENSIONS
    assert str(params.distance).lower().endswith("cosine")


@needs_qdrant
def test_a_dimensionality_mismatch_is_refused(indexed: tuple[str, Embedder]) -> None:
    """The one-way door, guarded. Writing 768 vectors into a collection of another width
    is not recoverable without re-embedding every corpus."""
    with pytest.raises(RuntimeError, match="re-embedding every corpus"):
        ensure_collection(client(), EmbeddingConfig(model="x", dimensions=384))


# ------------------------------------------------------------------ retrieval


@needs_qdrant
def test_a_covered_question_retrieves_its_chunk(
    indexed: tuple[str, Embedder], lexical_floor: None
) -> None:
    owner, embedder = indexed
    found = retrieve(
        client(),
        embedder,
        corpus_id="c1",
        question="what does the lens do",
        name="Lens",
        aliases=["crystalline lens"],
    )
    assert found.covered
    assert "lens" in found.hits[0].text.lower()


@needs_qdrant
def test_an_uncovered_question_falls_below_the_floor(indexed: tuple[str, Embedder]) -> None:
    """Not an error and not an empty state — a first-class result (Rule 6)."""
    owner, embedder = indexed
    found = retrieve(
        client(),
        embedder,
        corpus_id="c1",
        question="how does mitochondrial respiration produce ATP",
        name="Mitochondrion",
        aliases=["mitochondria"],
        floor=0.35,
    )
    assert not found.covered


@needs_qdrant
def test_retrieval_never_crosses_corpora(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """D-007. The filter is on the query, so another corpus is never a candidate."""
    owner, embedder = indexed
    found = retrieve(
        client(),
        embedder,
        corpus_id="some-other-corpus",
        question="what does the lens do",
        name="Lens",
    )
    assert found.hits == ()


# --------------------------------------------------- provenance resolution


def _hit(text: str, source: str = "digital", chunk_id: str = "c") -> Hit:
    return Hit(
        chunk_id=chunk_id,
        corpus_id="c1",
        document_id="d1",
        text=text,
        page_index=0,
        page_label="1",
        section=None,
        source=source,
        score=0.9,
    )


def test_unverified_resolves_to_strong_when_a_chunk_names_the_part() -> None:
    """D-030's second half: this is where chunk text finally exists."""
    resolved = resolve_provenance([_hit("The lens focuses light.")], ["Lens"])
    assert resolved.strength == "strong"
    assert resolved.source == "digital"
    assert resolved.display_confidence == "strong"


def test_unverified_resolves_to_weak_when_nothing_names_it() -> None:
    resolved = resolve_provenance([_hit("The retina contains rods and cones.")], ["Lens"])
    assert resolved.strength == "weak"


def test_no_evidence_at_all_is_none() -> None:
    assert resolve_provenance([], ["Lens"]).strength == "none"


def test_naming_is_whole_word_not_substring() -> None:
    """A false positive here promotes a part to `strong` on evidence that never mentions
    it — the fabricated-confidence failure D-030 exists to prevent.

    Note what this costs: "irises" does NOT match the term "iris", so an inflected form
    needs to be an alias. That is the designed mechanism (D5) rather than a gap — matching
    on substrings would make "iris" fire on "irishman", and a part promoted to `strong` by
    a coincidental prefix is exactly the failure being avoided.
    """
    assert resolve_provenance([_hit("The iris controls the pupil.")], ["iris"]).strength == "strong"
    assert resolve_provenance([_hit("An irishman walked in.")], ["iris"]).strength == "weak"
    # Inflected forms are reached through aliases, not through loose matching.
    assert (
        resolve_provenance([_hit("The irises contract.")], ["iris", "irises"]).strength == "strong"
    )


def test_ocr_derived_strength_is_reported_differently(conn: sqlite3.Connection) -> None:
    """D-044: source is a SECOND AXIS, not more states.

    The claim is equally strong; the reading of it is not. Collapsing these would make
    "strong regardless of how we read it" inexpressible.
    """
    digital = resolve_provenance([_hit("The lens focuses light.", "digital")], ["Lens"])
    ocr = resolve_provenance([_hit("The lens focuses light.", "ocr")], ["Lens"])

    assert digital.strength == ocr.strength == "strong"  # same axis
    assert digital.source != ocr.source  # different axis
    assert ocr.display_confidence == "strong (OCR)"
    assert digital.display_confidence == "strong"


def test_disagreeing_sources_are_mixed_not_arbitrary() -> None:
    resolved = resolve_provenance(
        [
            _hit("The lens focuses light.", "digital", "a"),
            _hit("The lens is biconvex.", "ocr", "b"),
        ],
        ["Lens"],
    )
    assert resolved.source == "mixed"
    assert resolved.display_confidence == "strong (partly OCR)"
    assert combine_sources(["digital", "digital"]) == "digital"
    assert combine_sources([]) == "unknown"


def test_only_cited_chunks_count_when_a_spec_supplied_them() -> None:
    hits = [_hit("The lens focuses light.", chunk_id="cited"), _hit("Unrelated.", chunk_id="other")]
    assert resolve_provenance(hits, ["Lens"], cited_chunk_ids=["cited"]).strength == "strong"
    assert resolve_provenance(hits, ["Lens"], cited_chunk_ids=["other"]).strength == "weak"
    assert resolve_provenance(hits, ["Lens"], cited_chunk_ids=["absent"]).strength == "none"


# ------------------------------------------------------------------- /ask


@needs_qdrant
def test_ask_answers_from_the_chapter_and_cites_the_page_LABEL(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection, lexical_floor: None
) -> None:
    """2C.5. The label is what the student can look up; the index is an implementation
    detail that happens to be off by one here."""
    owner, embedder = indexed
    answer = ask(
        conn,
        client(),
        embedder,
        owner_id=owner,
        corpus_id="c1",
        topic_id="t1",
        question="what does the lens do",
        part_id="lens",
        name="Lens",
        aliases=["crystalline lens"],
    )
    assert answer.kind == "generated"
    assert answer.citations
    first = answer.citations[0]
    assert first.render() == f"[p. {first.page_label}]"
    # The rendered citation must never be the index.
    assert str(first.page_index) not in first.render() or first.page_label == str(first.page_index)
    assert "12" in answer.cited_pages or "13" in answer.cited_pages


@needs_qdrant
def test_ask_returns_not_in_chapter_rather_than_fabricating(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    owner, embedder = indexed
    answer = ask(
        conn,
        client(),
        embedder,
        owner_id=owner,
        corpus_id="c1",
        topic_id="t1",
        question="explain the Krebs cycle in mitochondria",
        part_id="mito",
        name="Mitochondrion",
        aliases=["mitochondria"],
    )
    assert answer.kind == "not_in_chapter"
    assert answer.citations == (), "an uncovered question must cite nothing"
    assert "does not appear to cover" in answer.text


@needs_qdrant
def test_a_cache_hit_consumes_no_quota_and_no_budget(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection, lexical_floor: None
) -> None:
    """The ordering IS the design: the cache lookup sits above quota and budget."""
    owner, embedder = indexed

    first = ask(
        conn,
        client(),
        embedder,
        owner_id=owner,
        corpus_id="c1",
        topic_id="t1",
        question="what does the lens do",
        part_id="lens",
        name="Lens",
        aliases=["crystalline lens"],
    )
    assert first.kind == "generated"
    assert not first.from_cache

    # A quota of zero refuses any billable question. The repeat must still succeed, which
    # it can only do if the cache lookup happens before the quota check.
    second = ask(
        conn,
        client(),
        embedder,
        owner_id=owner,
        corpus_id="c1",
        topic_id="t1",
        question="what does the lens do",
        part_id="lens",
        name="Lens",
        aliases=["crystalline lens"],
        quota=OwnerQuota(max_questions_per_day=0),
    )

    assert second.from_cache
    assert second.kind == "cached"
    assert second.citations, "a cached answer keeps its citations"


@needs_qdrant
def test_a_billable_question_does_respect_the_quota(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """Guards the guard: if the quota were never checked, the test above proves nothing."""
    owner, embedder = indexed
    from aakar.providers import Usage

    ledger = CostLedger(conn, owner, max_usd_per_run=100.0)
    ledger.record(
        kind="chat",
        model="m",
        mode="live",
        usage=Usage(usd=0.01),
        request_hash="h",
        cache_hit=False,
        tier="answer",
    )
    with pytest.raises(QuotaExceeded):
        ask(
            conn,
            client(),
            embedder,
            owner_id=owner,
            corpus_id="c1",
            topic_id="t1",
            question="a question never asked before about the cornea",
            part_id="cornea",
            name="Cornea",
            quota=OwnerQuota(max_questions_per_day=1),
        )


@needs_qdrant
def test_an_owner_without_a_grant_is_refused(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """Access is by grant, never by ownership (D-029)."""
    owner, embedder = indexed
    stranger = ensure_owner(conn, "stranger@example.com", "password-stranger-long-enough")
    with pytest.raises(NotPermitted):
        ask(
            conn,
            client(),
            embedder,
            owner_id=stranger,
            corpus_id="c1",
            topic_id="t1",
            question="what does the lens do",
            part_id="lens",
            name="Lens",
        )


# ------------------------------------------- D-049 fresh/cached equivalence


#: Fields a cached answer is ALLOWED to differ on, with the reason. **Everything else** —
#: every dataclass field and every derived property of `Answer` — must be identical between
#: the answer the first student gets and the one the second student gets.
#:
#: The list is inverted on purpose. An allowlist of *comparisons* would silently stop
#: covering a field added later; an allowlist of *exemptions* means a new field is compared
#: by default, so one added without a stored counterpart fails here immediately instead of
#: degrading on the second student's question, which is where nobody is looking.
ALLOWED_TO_DIFFER = {
    "kind": "'cached' is the point — it is what tells the panel nothing was spent",
    "from_cache": "the flag whose whole job is to differ",
    "similar_question": "only a cache hit can have matched a paraphrase (D4)",
    "retrieval": "an internal handle on the search, never shown and never stored",
}


def _comparable(answer: Answer) -> dict[str, object]:
    """Every dataclass field and every public property, minus the exemptions."""
    names = {f.name for f in dataclasses.fields(answer)}
    names |= {n for n, v in vars(type(answer)).items() if isinstance(v, property)}
    return {n: getattr(answer, n) for n in sorted(names) if n not in ALLOWED_TO_DIFFER}


def test_the_divergence_exemptions_name_real_fields() -> None:
    """Guards the guard: a typo in `ALLOWED_TO_DIFFER` would silently exempt nothing while
    looking like it exempted something, and the reverse — a renamed field — would leave a
    dead exemption quietly widening as the class changes around it."""
    answer = Answer(kind="generated", text="x")
    names = {f.name for f in dataclasses.fields(answer)}
    names |= {n for n, v in vars(Answer).items() if isinstance(v, property)}
    assert set(ALLOWED_TO_DIFFER) <= names
    assert len(_comparable(answer)) >= 5, "the comparison must actually cover something"


@needs_qdrant
def test_a_cached_answer_is_field_for_field_identical_to_a_fresh_one(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """D-049. The property behind the `display_confidence` drop, generalised.

    Anything computed at answer time and not stored vanishes on the second student's
    question, and every fresh-path test stays green while it does. So the invariant is not
    "provenance survives the cache" — that is one instance — it is **fresh == cached, field
    by field**, driven by the field list rather than by whichever fields someone remembered.

    The question deliberately reaches the OCR chunk, because the source axis is the part
    most likely to be reconstructed rather than stored.
    """
    owner, embedder = indexed
    kwargs = {
        "owner_id": owner,
        "corpus_id": "c1",
        "topic_id": "t1",
        "question": "what fluid fills the anterior chamber?",
        "part_id": "aqueous",
        "name": "Aqueous humour",
        "aliases": ["aqueous humor"],
    }
    fresh = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]
    cached = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]

    assert fresh.kind == "generated"
    assert cached.kind == "cached" and cached.from_cache

    left, right = _comparable(fresh), _comparable(cached)
    differing = {k: (left[k], right[k]) for k in left if left[k] != right[k]}
    assert not differing, f"cached answer diverges from fresh: {differing}"


@needs_qdrant
def test_the_equivalence_check_can_see_a_dropped_field(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """R2. A comparison that never caught a divergence has not been shown to work.

    Drives the same comparison against a payload with the provenance deliberately stripped —
    exactly the shape a field added later without a stored counterpart would produce — and
    requires it to fail.
    """
    owner, embedder = indexed
    kwargs = {
        "owner_id": owner,
        "corpus_id": "c1",
        "topic_id": "t1",
        "question": "what fluid fills the anterior chamber?",
        "part_id": "aqueous",
        "name": "Aqueous humour",
    }
    fresh = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]

    conn.execute(
        "UPDATE qa_cache_meta SET answer_json = json_remove(answer_json, '$.provenance')",
    )
    conn.commit()
    degraded = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]

    left, right = _comparable(fresh), _comparable(degraded)
    assert {k: (left[k], right[k]) for k in left if left[k] != right[k]}, (
        "stripping the stored provenance produced no visible divergence, so the "
        "comparison would not catch a field added without a stored counterpart"
    )


@needs_qdrant
def test_an_uncovered_question_answers_the_same_way_every_time(
    indexed: tuple[str, Embedder], conn: sqlite3.Connection
) -> None:
    """`not_in_chapter` is never cached — there is nothing to spend and nothing to store.
    It must therefore be *reproducible* rather than *restored*, and the second student must
    get the same refusal rather than a different one."""
    owner, embedder = indexed
    kwargs = {
        "owner_id": owner,
        "corpus_id": "c1",
        "topic_id": "t1",
        "question": "what is the treatment for glaucoma?",
        "part_id": "glaucoma",
        "name": "Glaucoma",
    }
    first = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]
    second = ask(conn, client(), embedder, **kwargs)  # type: ignore[arg-type]
    assert first.kind == "not_in_chapter"
    assert second.kind == "not_in_chapter", "a refusal must not become a cache hit"
    assert _comparable(first) == _comparable(second)
