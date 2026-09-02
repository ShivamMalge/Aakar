"""3B — classification, provenance verification and the golden comparison, without a key.

The model is never called here. Every classifier is driven with documents built to land in
each bucket (R2): not JSON, schema-invalid, referentially invalid, valid; honest empty
provenance, fabricated citations, unknown chunks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aakar.config import REPO_ROOT
from aakar.generation import SYSTEM, build_prompt, classify, compare_to_golden, verify_provenance

GOLDEN = REPO_ROOT / "specs" / "golden"


def golden(topic: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((GOLDEN / f"{topic}.json").read_text(encoding="utf-8"))
    return loaded


def part(pid: str, name: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": pid,
        "name": name,
        "geometry": {"type": "sphere", "radius": 0.5},
        "material": {"color": "#aabbcc"},
        "provenance": {"chunk_ids": []},
    }
    return {**base, **extra}


def spec(*parts: dict[str, Any]) -> dict[str, Any]:
    # `topic` must match ^[a-z0-9_]{2,64}$ — a one-letter slug is schema-invalid on its own.
    return {"schema_version": "1.2", "topic": "test_topic", "title": "T", "parts": list(parts)}


CHUNKS = {
    "c01": ("541", "The outermost layer is the fibrous tunic, the white sclera and clear cornea."),
    "c08": ("544", "At the fovea, the retina lacks supporting cells; visual acuity is greatest."),
}


# ------------------------------------------------------------------ classify


def test_every_golden_spec_classifies_as_valid() -> None:
    """Guards the guard: a classifier that rejects the hand-written specs is broken."""
    for topic in ("human_eye", "animal_cell", "earth_layers"):
        o = classify(json.dumps(golden(topic)))
        assert o.schema_valid and o.referential_valid and o.valid, topic


def test_not_json_is_its_own_bucket() -> None:
    o = classify("Here is your spec:\n{not json")
    assert o.document is None and o.parse_error and not o.schema_valid


def test_code_fences_are_stripped_not_counted_as_failure() -> None:
    fenced = "```json\n" + json.dumps(golden("earth_layers")) + "\n```"
    assert classify(fenced).valid


def test_schema_invalid_is_distinguished_from_referential_invalid() -> None:
    bad_geometry = spec(part("a", "A", geometry={"type": "blob", "radius": 1}))
    o = classify(json.dumps(bad_geometry))
    assert not o.schema_valid and o.schema_errors

    dangling = spec(part("a", "A"), part("b", "B", parent_id="nope"))
    o = classify(json.dumps(dangling))
    assert o.schema_valid, "the document holds the schema"
    assert not o.referential_valid and "parent_not_found" in " ".join(o.referential_errors)
    assert not o.valid


def test_a_cycle_is_referentially_invalid() -> None:
    cyc = spec(part("a", "A", parent_id="b"), part("b", "B", parent_id="a"))
    o = classify(json.dumps(cyc))
    assert o.schema_valid and not o.referential_valid


# ------------------------------------------------------------------ provenance


def test_verify_provenance_separates_honest_fabricated_and_unknown() -> None:
    doc = spec(
        part("sclera", "Sclera", provenance={"chunk_ids": ["c01"]}),  # c01 names it
        part("fovea", "Fovea", provenance={"chunk_ids": ["c01"]}),  # c01 does NOT
        part("lens", "Lens", provenance={"chunk_ids": []}),  # honest
        part("iris", "Iris", provenance={"chunk_ids": ["c99"]}),  # not a chunk
    )
    o = verify_provenance(classify(json.dumps(doc)), CHUNKS)
    assert o.zero_provenance == ("lens",)
    assert o.fabricated == (("fovea", "c01"),)
    assert o.unknown_chunks == (("iris", "c99"),)


def test_an_alias_can_carry_a_citation() -> None:
    """The chunk says "fovea"; the part is named "Macula" with "fovea" as an alias. Same
    whole-word test provenance uses later, so a citation this passes is one the product
    would credit."""
    doc = spec(part("m", "Macula", aliases=["fovea"], provenance={"chunk_ids": ["c08"]}))
    o = verify_provenance(classify(json.dumps(doc)), CHUNKS)
    assert not o.fabricated


# ------------------------------------------------------------------ comparison


def test_self_comparison_is_empty_both_ways() -> None:
    c = compare_to_golden(golden("human_eye"), golden("human_eye"))
    assert c.only_in_golden == () and c.only_in_generated == ()
    assert len(c.matched) == 12


def test_comparison_matches_on_aliases_and_inflections() -> None:
    gen = spec(
        part("vh", "Vitreous humor"),  # golden says "Vitreous humour"
        part("pupil", "Pupil"),
        part("zonules", "Suspensory ligaments"),  # not in golden
    )
    c = compare_to_golden(gen, golden("human_eye"))
    matched_gold = {g for g, _ in c.matched}
    assert {"Vitreous Humour", "Pupil"} <= matched_gold, "matched across -or/-our and case"
    assert "Suspensory ligaments" in c.only_in_generated
    assert "Sclera" in c.only_in_golden


def test_shape_and_geometry_are_reported_not_scored() -> None:
    c = compare_to_golden(golden("earth_layers"), golden("human_eye"))
    assert c.golden_shape.parts == 12 and c.golden_shape.with_parent == 1
    assert c.generated_shape.parts == 5 and c.generated_shape.max_depth == 0
    assert c.generated_geometry == {"sphere": 5}


# ------------------------------------------------------------------ the prompt


def test_the_prompt_states_the_two_rules_that_fluent_models_break_first() -> None:
    assert "EMPTY list []" in SYSTEM
    assert "does NOT mean" in SYSTEM and "containment" in SYSTEM


def test_the_prompt_carries_schema_passages_and_structures_and_a_nonce() -> None:
    schema = json.loads((REPO_ROOT / "packages/scenespec/scenespec.schema.json").read_text("utf-8"))
    text = build_prompt(
        schema=schema,
        exemplar=golden("animal_cell"),
        exemplar_note="golden spec for animal_cell",
        topic="human_eye",
        title="The Human Eye",
        scale="the whole human eye",
        chunks=CHUNKS,
        structures=[
            {"name": "sclera", "kind": "structure", "naming_chunks": ["c01"], "aliases": []}
        ],
        nonce="3/10",
    )
    assert '"const":"1.2"' in text
    assert "[c01] (p. 541)" in text
    assert "- sclera (kind: structure; named in: c01" in text
    assert "(trial 3/10)" in text
    assert '"topic":"animal_cell"' in text and '"topic":"human_eye"' not in text.split("TOPIC:")[0]


def test_generated_specs_are_written_under_evidence(tmp_path: Path) -> None:
    """A gate the reader can open: every generation, valid or not, lands as a file."""
    assert (REPO_ROOT / "evidence").is_dir()
    assert tmp_path.is_dir()
