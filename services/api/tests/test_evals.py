"""2D.1 — the eval harnesses, and the proof that they can see a failure.

The whole risk with an eval is that it reports zeros because nothing is wrong *and* because
it stopped looking, and those read identically. So every count here is tested by an answer
built to trigger it (R2), and the fixtures live in `evals/golden-provenance/answers.json`
next to the golden set rather than inline, because they are data a human has to read.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from aakar.evals import faithfulness as f
from aakar.evals.embedders import EMBEDDERS, embedder_from_env, resolve_embedder
from aakar.evals.golden import GOLDEN_DIR, load_answers, load_golden_set, rank
from aakar.evals.run import grade, main
from aakar.evals.thresholds import calibrate_relevance_floor
from aakar.providers import ProviderError
from aakar.rag.answer import build_prompt
from aakar.rag.ask import Answer, Citation, ask
from aakar.rag.cache import scope_key, store
from aakar.rag.embedding import Embedder, local_embed
from aakar.rag.index import Hit
from aakar.rag.provenance_resolve import ResolvedProvenance
from aakar.rag.retrieval import DEFAULT_FLOOR


def chunk(chunk_id: str, text: str, *, source: str = "digital", page: str = "1") -> Hit:
    return Hit(
        chunk_id=chunk_id,
        corpus_id="c",
        document_id="d",
        text=text,
        page_index=0,
        page_label=page,
        section=None,
        source=source,
        score=1.0,
    )


# ------------------------------------------------------------------ marker parsing


def test_a_multi_marker_names_every_passage_in_it() -> None:
    """``[2,3]`` is two citations, not one. Counting it as one would let half a bad
    citation hide behind a good one."""
    hits = {1: chunk("a", "alpha"), 2: chunk("b", "beta"), 3: chunk("c", "gamma")}
    report = f.evaluate_answer("The beta and gamma are related [2,3].", hits)
    assert report.sentences[0].markers == (2, 3)


def test_markers_are_stripped_before_the_sentence_is_judged() -> None:
    """A marker is not evidence about its own sentence. Leaving ``[1]`` in the text would
    add a token to both sides of the overlap and inflate every score slightly."""
    report = f.evaluate_answer("The lens focuses light [1].", {1: chunk("a", "the lens focuses")})
    assert report.sentences[0].sentence == "The lens focuses light."


# ------------------------------------------------------------------ the three counts


def test_count_1_an_invented_marker() -> None:
    """A marker naming a passage that was never in the prompt."""
    report = f.evaluate_answer("The choroid supplies blood [7].", {1: chunk("a", "choroid blood")})
    assert report.unresolvable_markers == 1
    assert report.sentences[0].unresolvable == (7,)


def test_count_2_fluent_correct_and_cited_to_the_wrong_chunk() -> None:
    """THE case. True sentence, real marker, wrong passage. Nothing about it looks wrong."""
    numbering = {
        1: chunk("c07", "The photoreceptors change their membrane potential when stimulated."),
        2: chunk("c03", "The choroid provides a blood supply to the eyeball."),
    }
    report = f.evaluate_answer(
        "The choroid provides the blood supply to the eyeball [1].", numbering
    )
    assert report.unsupported_sentences == 1
    assert report.unresolvable_markers == 0, "the marker resolves; that is what makes it nasty"
    # The evidence exists — in passage 2. Reporting where it actually is turns the count
    # into something someone can act on.
    assert report.sentences[0].pool_match == "c03"


def test_count_3_a_claim_that_is_in_no_chunk_at_all() -> None:
    report = f.evaluate_answer(
        "The sclera is roughly 0.5 millimetres thick at the equator of the eye.",
        {1: chunk("c01", "The outermost layer is the fibrous tunic, the white sclera.")},
    )
    assert report.uncited_claims == 1
    assert report.missing_markers == 0


def test_an_uncited_but_true_claim_is_not_counted_as_fabrication() -> None:
    """The distinction count 3 exists to preserve: a missing marker is a prompt problem, a
    fabrication is a grounding problem, and one number for both hides which you have."""
    report = f.evaluate_answer(
        "The eye has three layers of tissue.",
        {1: chunk("c01", "The eye itself is a hollow sphere composed of three layers of tissue.")},
    )
    assert report.missing_markers == 1
    assert report.uncited_claims == 0


def test_a_refusal_is_not_an_uncited_claim() -> None:
    """Rule 6's answer must not be scored as a failure — that would penalise the single
    behaviour this design exists to produce."""
    report = f.evaluate_answer(
        "Your chapter does not cover retinal detachment. "
        "The passages describe the retina but say nothing about its causes.",
        {1: chunk("c05", "The innermost layer of the eye is the neural tunic, or retina.")},
    )
    assert report.clean
    assert report.claims == 0


def test_a_faithful_answer_moves_no_count() -> None:
    """Guards the guard: a harness that flagged everything would pass every test above."""
    report = f.evaluate_answer(
        "The pupil is the hole at the center of the eye that allows light to enter [1].",
        {
            1: chunk(
                "c04",
                "the pupil, which is the hole at the center of the eye that allows light to enter",
            )
        },
    )
    assert report.clean
    assert report.supported == 1


def test_ambiguous_support_is_escalated_rather_than_guessed() -> None:
    """Between the two thresholds the harness says "a human should read this" instead of
    picking whichever answer flatters the run."""
    report = f.evaluate_answer(
        "The vascular tunic contains the choroid and supplies blood to unrelated tissue [1].",
        {1: chunk("c03", "The middle layer is the vascular tunic, mostly the choroid.")},
    )
    verdict = report.sentences[0]
    assert f.UNCERTAIN <= verdict.overlap < f.SUPPORTED_AT
    assert verdict.verdict == "uncertain"
    assert report.needs_human == 1
    assert report.clean, "uncertainty escalates; it does not fail the run"


def test_supports_is_a_lower_bound_not_a_judgement() -> None:
    """A paraphrase sharing no words scores zero. Documented, not a bug — it is why a zero
    count 2 is a floor rather than a proof."""
    assert (
        f.supports(
            "Light is bent onto the back of the eye.", "The cornea focuses light onto the retina."
        )
        < f.SUPPORTED_AT
    )


# ------------------------------------------------------------------ the golden set


def test_the_golden_set_is_marked_unverified_and_says_so() -> None:
    """It ships PROPOSED. Anything derived from it is provisional until a human signs it."""
    golden = load_golden_set()
    assert golden.verified is False
    assert golden.provisional is True
    assert len(golden.questions) == 15
    assert len(golden.chunks) == 10


def test_the_golden_set_exercises_the_ocr_path() -> None:
    """D-044 needs at least one OCR chunk or the display path is never reached."""
    assert load_golden_set().ocr_chunk_ids == ("c06",)


def test_every_not_in_chapter_question_names_a_part_the_chapter_discusses() -> None:
    """A hard negative that names something absent is easy and proves nothing. Each of these
    names a real part and asks something the chapter never says."""
    golden = load_golden_set()
    corpus = " ".join(c.text.lower() for c in golden.chunks)
    negatives = [q for q in golden.questions if not q.answerable]
    assert len(negatives) == 5
    for question in negatives:
        assert question.part.lower() in corpus, f"{question.id} is too easy a negative"


def test_a_set_claiming_verification_with_nobody_behind_it_is_refused(tmp_path: Path) -> None:
    """Worse than unverified: it looks like evidence and cannot be chased down."""
    questions = json.loads((GOLDEN_DIR / "questions.json").read_text(encoding="utf-8"))
    questions["verified"] = True
    (tmp_path / "questions.json").write_text(json.dumps(questions), encoding="utf-8")
    (tmp_path / "chapter.json").write_text(
        (GOLDEN_DIR / "chapter.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no one accountable"):
        load_golden_set(tmp_path)


def test_the_ranker_scores_with_the_same_numbering_the_prompt_uses() -> None:
    """The eval and the prompt must agree about what ``[1]`` means, or every count is
    graded against a scheme the model was never given."""
    golden = load_golden_set()
    embed = resolve_embedder("local").build()
    vectors = [embed.document(c.text) for c in golden.chunks]
    ranked = rank(embed.query("what is the pupil"), golden.chunks, vectors)
    prompt = build_prompt("what is the pupil", ranked[:3])
    assert prompt.numbering[1] is ranked[0]
    assert set(prompt.numbering) == {1, 2, 3}


# ------------------------------------------------------------------ the fixtures fire


@pytest.mark.parametrize("fixture", load_answers(), ids=lambda a: a.id)
def test_each_answer_fixture_triggers_the_count_it_was_built_for(fixture: object) -> None:
    """The regression guard on the harness itself. If a change stops the harness seeing a
    miscitation, this fails instead of the run quietly reporting zeros."""
    golden = load_golden_set()
    report = grade(fixture, golden, embedder=resolve_embedder("local"))  # type: ignore[arg-type]
    fired = {
        "unresolvable_markers": report.unresolvable_markers,
        "unsupported_sentences": report.unsupported_sentences,
        "uncited_claims": report.uncited_claims,
        "missing_markers": report.missing_markers,
    }
    expect = fixture.expect  # type: ignore[attr-defined]
    if expect == "clean":
        assert report.clean and report.missing_markers == 0, fired
    else:
        assert fired[expect], f"{expect} did not fire: {fired}"


def test_grading_a_fixture_inherits_the_provisional_flag() -> None:
    """A number cannot escape its caveat by being copied out of a terminal."""
    golden = load_golden_set()
    report = grade(load_answers()[0], golden, embedder=resolve_embedder("local"))
    assert report.provisional
    assert "PROVISIONAL" in f.format_report(report)


# ------------------------------------------------------------------ 2D.1d, embedders


def test_the_local_embedder_refuses_to_certify_a_threshold() -> None:
    """It is lexical. A threshold measured on it describes string matching, not meaning."""
    local = resolve_embedder("local")
    assert local.calibrating is False
    assert local.caveat


def test_the_shipping_embedder_needs_no_key_in_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """2D.2e, as a test rather than an assertion in a report: the real embedder is reachable
    through the cassette with no key at all, which is what lets CI re-run every 2D.2
    measurement for free."""
    monkeypatch.delenv("AAKAR_API_KEY", raising=False)
    monkeypatch.setenv("AAKAR_PROVIDER_MODE", "replay")
    assert EMBEDDERS["gemini"].build() is not None


def test_the_shipping_embedder_refuses_to_record_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And it still refuses rather than falling back to `local`. A silent fallback would let
    every harness keep printing numbers while measuring the stub — the exact confusion the
    2D.1/2D.2 split exists to prevent."""
    monkeypatch.delenv("AAKAR_API_KEY", raising=False)
    monkeypatch.setenv("AAKAR_PROVIDER_MODE", "record")
    with pytest.raises(ProviderError, match="AAKAR_API_KEY"):
        EMBEDDERS["gemini"].build()


def test_the_default_is_the_one_that_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AAKAR_EVAL_EMBEDDER", raising=False)
    assert embedder_from_env().name == "local"


def test_swapping_the_embedder_is_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """2D.1d in one line: the harness reads which embedder to use, it does not import one."""
    monkeypatch.setenv("AAKAR_EVAL_EMBEDDER", "gemini")
    assert embedder_from_env().name == "gemini"


def test_an_unknown_embedder_names_the_ones_that_exist() -> None:
    with pytest.raises(KeyError, match="local"):
        resolve_embedder("word2vec")


# ------------------------------------------------------------------ the floor sweep


def test_the_floor_sweep_treats_false_coverage_as_binding() -> None:
    """Same rule as the cache threshold: zero, absolute, not a rate. One uncovered question
    answered confidently is the failure the floor exists to prevent."""
    calibration = calibrate_relevance_floor(embedder=resolve_embedder("local"))
    for result in calibration.results:
        assert result.acceptable == (result.false_coverage == 0)
    best = calibration.recommended
    assert best is not None
    assert best.false_coverage == 0
    assert all(r.floor >= best.floor for r in calibration.results if r.acceptable)


def test_the_sweep_actually_refuses_something_at_a_high_floor() -> None:
    """R2: a floor that never refused is untested. The sweep must span a range where the
    negatives are rejected, or it is measuring nothing."""
    calibration = calibrate_relevance_floor(embedder=resolve_embedder("local"))
    assert any(r.false_coverage > 0 for r in calibration.results), "no floor was too low"
    assert any(r.missed > 0 for r in calibration.results), "no floor was too high"


def test_the_scope_limits_are_recorded_and_reach_the_report() -> None:
    """Both limits the architect named must be in the file AND printed by the runner.

    A caveat that lives only in a JSON file is a caveat that gets skipped the first time
    someone copies a number out of a terminal — which is exactly how a ceiling becomes a
    typical case in someone's memory.
    """
    limits = load_golden_set().scope_limits
    numbered = {k: v for k, v in limits.items() if k[:1].isdigit()}
    assert len(numbered) == 2, "one limit per architect ruling: clean corpus, and clean OCR"
    joined = " ".join(numbered.values()).lower()
    assert "scanned indian textbook" in joined
    assert "c06" in joined and "artefact" in joined

    out = io.StringIO()
    main(out)
    printed = out.getvalue()
    assert printed.count("scope limit") == 2


def test_the_shipped_default_floor_both_admits_and_refuses() -> None:
    """R1 and R2 on `DEFAULT_FLOOR` itself (D-050).

    A floor is trivially "safe" at 1.0, where it refuses everything and answers nothing. So
    the shipped default has to be shown doing both halves of its job on a real chapter: it
    must refuse every one of the five hard negatives, and it must still admit real
    questions. The number stays PROVISIONAL — this is the local lexical embedder — but the
    *shape* of the requirement does not depend on the embedder, and this is the test that
    fails loudly if 2D.2's measurement moves the default somewhere useless.
    """
    calibration = calibrate_relevance_floor(embedder=resolve_embedder("local"))
    shipped = next(r for r in calibration.results if r.floor == DEFAULT_FLOOR)
    assert shipped.false_coverage == 0, f"the default admits {shipped.false_ids}"
    assert shipped.covered > 0, "a floor that admits nothing is not a floor, it is an outage"


def test_raising_the_floor_is_what_closed_the_false_coverage() -> None:
    """Records the finding behind D-050 as an executable fact, not a note in a file: the
    previous default of 0.35 admitted questions this chapter cannot answer, and 0.45 is the
    lowest swept value that admits none. If a future change makes 0.35 safe again, this
    fails and the decision gets revisited deliberately."""
    calibration = calibrate_relevance_floor(embedder=resolve_embedder("local"))
    previous = next(r for r in calibration.results if r.floor == 0.35)
    assert previous.false_coverage > 0, "0.35 was picked without measurement; this is why"
    assert DEFAULT_FLOOR == 0.45


def test_the_floor_result_carries_its_embedder_and_verification_state() -> None:
    calibration = calibrate_relevance_floor(embedder=resolve_embedder("local"))
    assert calibration.provisional
    assert calibration.golden_verified is False
    assert "local" in calibration.embedder.label


# ------------------------------------------------------------------ 2D.1e, OCR display


def test_an_ocr_citation_does_not_render_like_a_digital_one() -> None:
    """The student checking page 543 needs to know it came out of an OCR engine. An
    answer-level warning says something is uncertain but not which page to distrust."""
    digital = Citation(chunk_id="c01", page_index=0, page_label="541", source="digital")
    scanned = Citation(chunk_id="c06", page_index=2, page_label="543", source="ocr")
    assert digital.render() == "[p. 541]"
    assert scanned.render() == "[p. 543, scanned]"
    # And still the label, never the index.
    assert "2" not in scanned.render()


def test_an_answer_showing_a_scanned_page_never_reads_as_plain_strong() -> None:
    """The gap this closes: provenance reads its source from the chunks that NAME the part,
    which can be entirely digital while a scanned page is still put in front of the reader."""
    answer = Answer(
        kind="generated",
        text="...",
        citations=(
            Citation(chunk_id="c01", page_index=0, page_label="541", source="digital"),
            Citation(chunk_id="c06", page_index=2, page_label="543", source="ocr"),
        ),
        provenance=ResolvedProvenance(strength="strong", source="digital"),
    )
    assert answer.provenance is not None
    assert answer.provenance.display_confidence == "strong"
    assert answer.display_confidence == "strong (partly OCR)"
    assert answer.scanned_pages == ("543",)


def test_wholly_ocr_evidence_is_not_softened_by_digital_pages_beside_it() -> None:
    """``strong (OCR)`` must not decay to ``strong (partly OCR)`` because an unrelated
    digital chunk was also retrieved: the claim still rests entirely on machine-read text."""
    answer = Answer(
        kind="generated",
        text="...",
        citations=(
            Citation(chunk_id="c06", page_index=2, page_label="543", source="ocr"),
            Citation(chunk_id="c01", page_index=0, page_label="541", source="digital"),
        ),
        provenance=ResolvedProvenance(strength="strong", source="ocr"),
    )
    assert answer.display_confidence == "strong (OCR)"


def test_an_all_digital_answer_is_not_gratuitously_qualified() -> None:
    """Guards the guard: a rule that marked everything scanned would pass the two above."""
    answer = Answer(
        kind="generated",
        text="...",
        citations=(Citation(chunk_id="c01", page_index=0, page_label="541", source="digital"),),
        provenance=ResolvedProvenance(strength="strong", source="digital"),
    )
    assert answer.display_confidence == "strong"
    assert answer.scanned_pages == ()


def test_an_answer_with_no_provenance_says_unknown_rather_than_guessing() -> None:
    assert Answer(kind="cached", text="...").display_confidence == "unknown"


def test_the_ocr_fixture_answer_cites_the_scanned_chunk() -> None:
    """Ties 2D.1e back to the golden set: the OCR path is exercised by a real question,
    not only by a hand-built Citation."""
    golden = load_golden_set()
    fixture = next(a for a in load_answers() if a.id == "a08")
    cited = [golden.by_id(c) for c in fixture.passages]
    assert [c.source for c in cited] == ["ocr"]
    citation = Citation(
        chunk_id=cited[0].chunk_id,
        page_index=cited[0].page_index,
        page_label=cited[0].page_label,
        source=cited[0].source,
    )
    assert "scanned" in citation.render()


# ------------------------------------------- 2D.1e through the cache, no Qdrant needed


def _grant(conn: sqlite3.Connection, owner_id: str, corpus_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO corpora (id, content_hash, name) VALUES (?, ?, 'golden')",
        (corpus_id, f"{corpus_id}-hash"),
    )
    conn.execute(
        "INSERT INTO corpus_grants (id, corpus_id, owner_id) VALUES (?, ?, ?)",
        (f"g-{corpus_id}", corpus_id, owner_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO topics (id, owner_id, corpus_id, slug, title)"
        " VALUES ('t1', ?, ?, 'eye', 'Eye')",
        (owner_id, corpus_id),
    )
    conn.commit()


def test_a_cached_answer_keeps_its_ocr_warning(conn: sqlite3.Connection, owner_id: str) -> None:
    """The gap this closes: `strength` lives on the resolved provenance, which a cache hit
    never recomputes. Without persisting it, an answer read as `strong (OCR)` when first
    generated and `unknown` once cached — so the OCR warning survived exactly until the
    question became popular enough for a second student to ask it.

    Reaches `ask` without Qdrant on purpose: the cache branch returns before retrieval, so
    this exercises the real code path rather than a reimplementation of it.
    """
    _grant(conn, owner_id, "gold")
    question = "what fills the space behind the lens?"
    scope = scope_key("vitreous", None)
    store(
        conn,
        owner_id=owner_id,
        corpus_id="gold",
        topic_id="t1",
        scope=scope,
        question=question,
        # Embedded with the same function `ask` will use, so the probe is a verbatim hit
        # rather than a fixture that happens to clear the threshold.
        question_vector=local_embed(question),
        answer={
            "text": "The posterior cavity is filled with vitreous humor [p. 543, scanned].",
            "citations": [
                {
                    "chunk_id": "c06",
                    "page_index": 5,
                    "page_label": "543",
                    "source": "ocr",
                }
            ],
            "provenance": {
                "strength": "strong",
                "source": "ocr",
                "naming_chunk_ids": ["c06"],
                "retrieved_chunk_ids": ["c06"],
            },
        },
    )

    # An empty in-memory Qdrant: if the cache branch did not return here, retrieval would
    # find nothing and the answer would come back `not_in_chapter` instead of `cached`.
    answer = ask(
        conn,
        QdrantClient(location=":memory:"),
        Embedder(None),
        owner_id=owner_id,
        corpus_id="gold",
        topic_id="t1",
        question=question,
        part_id="vitreous",
        name="Vitreous humour",
    )
    assert answer.kind == "cached"
    assert answer.display_confidence == "strong (OCR)"
    assert answer.scanned_pages == ("543",)
    assert answer.citations[0].render() == "[p. 543, scanned]"


def test_a_cached_answer_from_before_this_change_says_unknown_not_strong(
    conn: sqlite3.Connection, owner_id: str
) -> None:
    """Rows written before `strength` was stored have no provenance to restore. Reporting
    `unknown` is the honest reading; inventing `strong` for a row that never recorded one
    would fabricate exactly the confidence this whole axis exists to qualify."""
    _grant(conn, owner_id, "gold2")
    scope = scope_key("lens", None)
    store(
        conn,
        owner_id=owner_id,
        corpus_id="gold2",
        topic_id="t1",
        scope=scope,
        question="what does the lens do?",
        question_vector=local_embed("what does the lens do?"),
        answer={"text": "It focuses light [p. 12].", "citations": []},
    )
    answer = ask(
        conn,
        QdrantClient(location=":memory:"),
        Embedder(None),
        owner_id=owner_id,
        corpus_id="gold2",
        topic_id="t1",
        question="what does the lens do?",
        part_id="lens",
        name="Lens",
    )
    assert answer.kind == "cached"
    assert answer.provenance is None
    assert answer.display_confidence == "unknown"
