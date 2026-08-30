"""D-045 — a pinned model that no longer exists must fail at boot, not at first call.

This is the test that would have caught the actual failure: `gemini-2.0-flash` and
`text-embedding-004` were both pinned, both already shut down, and nothing noticed because
every test runs in replay against a stub. Pinning protects against *drift*; it does nothing
about a pin to something that no longer exists, and from inside a replay-mode suite the two
are indistinguishable.
"""

from __future__ import annotations

from datetime import date

import pytest

from aakar.config import DEFAULT_EMBED_MODEL, DEFAULT_MODEL, DEFAULT_VLM_MODEL, Settings
from aakar.providers import (
    RETIRED_MODELS,
    RetiredModel,
    check_configured_models,
    check_model,
)
from aakar.rag.embedding import DEFAULT_DIMENSIONS, l2_normalize, local_embed


def test_no_shipped_default_is_a_retired_model() -> None:
    """The regression guard. Every default the project ships must be live."""
    for label, model in (
        ("AAKAR_MODEL", DEFAULT_MODEL),
        ("AAKAR_VLM_MODEL", DEFAULT_VLM_MODEL),
        ("AAKAR_EMBED_MODEL", DEFAULT_EMBED_MODEL),
    ):
        check_model(model, label=label)  # must not raise


def test_the_previously_shipped_defaults_are_now_refused() -> None:
    """Both of these were pinned in this repository, and both were already dead."""
    with pytest.raises(RetiredModel, match="2026-06-01"):
        check_model("gemini-2.0-flash", label="AAKAR_MODEL")
    with pytest.raises(RetiredModel, match="2026-01-14"):
        check_model("text-embedding-004", label="AAKAR_EMBED_MODEL")


def test_the_error_names_the_setting_and_the_replacement() -> None:
    """Knowing a model is retired is far less useful than knowing WHICH pin holds it."""
    with pytest.raises(RetiredModel) as raised:
        check_model("gemini-2.0-flash", label="AAKAR_VLM_MODEL")
    message = str(raised.value)
    assert "AAKAR_VLM_MODEL" in message
    assert "gemini-3.6-flash" in message


def test_a_model_before_its_shutdown_date_is_allowed() -> None:
    """Guards the guard: a registry that refuses everything passes the tests above.

    A retirement announced for the future is not yet a failure, and refusing early would
    force a migration on a schedule the provider did not set.
    """
    check_model("gemini-2.0-flash", label="AAKAR_MODEL", today=date(2026, 5, 31))
    with pytest.raises(RetiredModel):
        check_model("gemini-2.0-flash", label="AAKAR_MODEL", today=date(2026, 6, 1))


def test_an_unknown_model_is_not_refused() -> None:
    """The registry lists retirements, not an allow-list. A model it has never heard of is
    the normal case, and the live check is what covers those."""
    check_model("some-model-released-next-year", label="AAKAR_MODEL")


def test_settings_refuses_a_retired_pin_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot, not first use. `Settings.from_env` is on every startup path."""
    monkeypatch.setenv("AAKAR_MODEL", "gemini-2.0-flash")
    with pytest.raises(RetiredModel):
        Settings.from_env()


def test_settings_checks_the_answer_tier_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer tier can be pinned separately, so it needs its own check."""
    monkeypatch.setenv("AAKAR_ANSWER_MODEL", "text-embedding-004")
    with pytest.raises(RetiredModel, match="AAKAR_ANSWER_MODEL"):
        Settings.from_env()


def test_every_registry_entry_names_a_live_replacement() -> None:
    """A refusal without somewhere to go is a wall — and a replacement that is itself
    retired is worse, because it looks like an answer."""
    for model, retirement in RETIRED_MODELS.items():
        assert retirement.replacement, f"{model} has no replacement"
        assert retirement.replacement not in RETIRED_MODELS, (
            f"{model} points at {retirement.replacement}, which is itself retired"
        )


def test_check_configured_models_reports_what_it_checked() -> None:
    checked = check_configured_models({"A": DEFAULT_MODEL, "B": DEFAULT_EMBED_MODEL})
    assert checked == ["A", "B"]


# ------------------------------------------------------------ MRL normalization


def test_vectors_are_unit_length() -> None:
    """`gemini-embedding-001` does NOT normalize below its native 3072 dimensions.

    Cosine on an unnormalized vector still returns a number in [-1, 1]; it is simply the
    wrong number. Nothing raises, retrieval quietly degrades, and every symptom points at a
    weak embedder rather than at a missing division.
    """
    vector = local_embed("the lens focuses light onto the retina", DEFAULT_DIMENSIONS)
    assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-9)


def test_normalizing_is_idempotent() -> None:
    """Applied unconditionally rather than behind a model check, so there is no branch to
    get wrong when a future model changes its behaviour."""
    once = l2_normalize([3.0, 4.0])
    assert once == pytest.approx([0.6, 0.8])
    assert l2_normalize(once) == pytest.approx(once)


def test_a_zero_vector_does_not_divide_by_zero() -> None:
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_normalization_is_what_makes_magnitude_irrelevant() -> None:
    """Shows the failure being prevented rather than asserting the fix in the abstract."""
    same_direction_different_magnitude = ([3.0, 4.0], [6.0, 8.0])
    a, b = (l2_normalize(v) for v in same_direction_different_magnitude)
    assert a == pytest.approx(b)
    assert sum(x * x for x in a) == pytest.approx(1.0)
