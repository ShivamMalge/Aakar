"""2D.2 — the live provider, its pricing, and the key-exposure scanner.

Every test here runs with **no key and no network** (Rule: CI never needs the key). What is
under test is the arithmetic, the refusals and the redaction — the parts that decide whether
a real call is priced honestly and whether a credential can escape.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from aakar.evals import keyscan
from aakar.evals.embedders import Embedders, provider_embedder, resolve_embedder
from aakar.providers import (
    PRICING,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    ProviderError,
    UnpricedModel,
    VlmRequest,
    usd_for,
)
from aakar.providers.gemini import (
    BACKOFF_BASE_SECONDS,
    CHARS_PER_TOKEN,
    GeminiProvider,
    estimate_tokens,
    price_for,
)
from aakar.rag.embedding import DEFAULT_DIMENSIONS

# ------------------------------------------------------------------ pricing


def test_every_model_this_project_pins_has_a_price() -> None:
    """An unpriced model would have the ledger record $0.00 for a real call, which turns
    the budget guard into decoration — it can never trip on spend that is always zero."""
    from aakar.config import DEFAULT_EMBED_MODEL, DEFAULT_MODEL, DEFAULT_VLM_MODEL

    for model in (DEFAULT_MODEL, DEFAULT_VLM_MODEL, DEFAULT_EMBED_MODEL):
        assert price_for(model).input_per_m > 0


def test_an_unpriced_model_raises_rather_than_costing_nothing() -> None:
    with pytest.raises(UnpricedModel, match="no price recorded"):
        usd_for("gemini-9.9-imaginary", 1000, 1000)


def test_the_arithmetic_is_per_million_tokens() -> None:
    """Guards a units error that would be invisible: a factor of a million in either
    direction still produces a plausible-looking small number."""
    price = PRICING["gemini-3.6-flash"]
    assert price.input_per_m == 0.75
    assert price.output_per_m == 3.75
    # 1M in, 1M out.
    assert usd_for("gemini-3.6-flash", 1_000_000, 1_000_000) == pytest.approx(4.50)
    assert usd_for("gemini-3.6-flash", 1000, 0) == pytest.approx(0.00075)


def test_an_embedding_model_has_no_output_price() -> None:
    """It produces vectors, not tokens. A non-zero output rate would silently inflate every
    embedding call by a cost that does not exist."""
    assert PRICING["gemini-embedding-001"].output_per_m == 0.0
    assert usd_for("gemini-embedding-001", 1_000_000, 999) == pytest.approx(0.15)


def test_token_estimation_is_only_used_where_the_provider_counts_nothing() -> None:
    """`batchEmbedContents` returns no usageMetadata. The estimate is documented as an
    estimate; this pins the rule so it cannot drift into looking like a measurement."""
    assert estimate_tokens("a" * (CHARS_PER_TOKEN * 10)) == 10
    assert estimate_tokens("") == 1, "never zero: a call that happened costs something"


# ------------------------------------------------------------------ refusals


def test_the_provider_refuses_to_exist_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructed only in live/record. Failing here rather than at first call is what keeps
    a misconfigured run from getting halfway through a corpus before it stops."""
    monkeypatch.delenv("AAKAR_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="AAKAR_API_KEY"):
        GeminiProvider()


def test_the_key_is_redacted_from_anything_the_provider_says() -> None:
    """Provider error bodies are echoed into exceptions. If one ever contained the key —
    a reflected request, a verbose gateway — the exception would carry it into a log."""
    provider = GeminiProvider(api_key="SECRET-KEY-VALUE")
    assert "SECRET-KEY-VALUE" not in provider._redact("error at ?key=SECRET-KEY-VALUE&x=1")
    assert "<AAKAR_API_KEY>" in provider._redact("?key=SECRET-KEY-VALUE")


def test_backoff_grows_and_is_jittered() -> None:
    """Lockstep retries re-hit a per-minute limit at exactly the same instant every time."""
    provider = GeminiProvider(api_key="k")
    first = [provider._backoff(1) for _ in range(20)]
    assert min(first) >= BACKOFF_BASE_SECONDS
    assert len(set(first)) > 1, "no jitter"
    assert provider._backoff(4) > max(first)


def test_the_provider_prefers_its_own_retry_delay() -> None:
    """It knows when the window reopens; a guessed backoff either wastes time or retries
    into the same refusal."""
    provider = GeminiProvider(api_key="k")
    body = '{"error": {"details": [{"retryDelay": "17s"}]}}'
    assert provider._retry_delay(body, 1) == pytest.approx(18.0)
    # Malformed bodies fall back rather than crashing inside error handling.
    assert provider._retry_delay("not json", 1) >= BACKOFF_BASE_SECONDS


# ------------------------------------------- documents and queries are not the same call


def test_a_provider_embedder_sends_different_task_types() -> None:
    """The bug this shape exists to prevent: the golden harness embedded CHUNK TEXT through
    the query path. The local stub has no task type, so it was invisible on the only
    embedder available before a key existed."""
    seen: list[str | None] = []

    class Recording:
        """Width-matched to production (D-043) rather than the stub's 32, because
        `Embedder` refuses a vector of the wrong width — as it should."""

        def chat(self, req: ChatRequest) -> ChatResponse:  # pragma: no cover - unused
            raise NotImplementedError

        def vlm(self, req: VlmRequest) -> ChatResponse:  # pragma: no cover - unused
            raise NotImplementedError

        def embed(self, req: EmbedRequest) -> EmbedResponse:
            seen.append(req.task_type)
            width = req.output_dimensionality or DEFAULT_DIMENSIONS
            return EmbedResponse(vectors=tuple((1.0,) * width for _ in req.texts))

    embedders = provider_embedder(Recording())
    embedders.query("a question")
    embedders.document("a passage")
    assert seen == ["RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"]


def test_the_local_embedder_is_the_same_function_on_both_sides() -> None:
    """Stated rather than left to look like an oversight: the stub has no task type."""
    both = resolve_embedder("local").build()
    assert isinstance(both, Embedders)
    assert list(both.query("the lens")) == list(both.document("the lens"))


# ------------------------------------------------------------------ the key scanner


def _planted(tmp_path: Path, key: str) -> Path:
    (tmp_path / "services" / "api" / "tests" / "cassettes" / "embed").mkdir(parents=True)
    (tmp_path / "services/api/tests/cassettes/embed/x.json").write_text(
        '{"vectors": [[0.1]], "leaked": "' + key + '"}', encoding="utf-8"
    )
    return tmp_path


def test_the_scanner_finds_a_planted_key_in_a_cassette(tmp_path: Path) -> None:
    """R2. A scanner that has never found anything has not been shown to work, and this one
    exists to be believed when it says ALL CLEAR."""
    key = "PLANTED-KEY-000000000000000000000000"
    out = io.StringIO()
    assert keyscan.check_cassettes(_planted(tmp_path, key), key, out) is False
    assert "FAIL" in out.getvalue()


def test_the_scanner_passes_a_clean_cassette(tmp_path: Path) -> None:
    """Guards the guard: a scanner that failed unconditionally would pass the test above."""
    _planted(tmp_path, "PLANTED-KEY-000000000000000000000000")
    out = io.StringIO()
    assert keyscan.check_cassettes(tmp_path, "A-DIFFERENT-VALUE-ENTIRELY", out) is True


def test_the_scanner_never_prints_the_key(tmp_path: Path) -> None:
    """A leak-detector that prints the leak is not a detector — the report itself would
    then be the thing that must not be shared."""
    key = "PLANTED-KEY-000000000000000000000000"
    out = io.StringIO()
    keyscan.check_cassettes(_planted(tmp_path, key), key, out)
    keyscan.check_working_tree(_planted(tmp_path / "b", key), key, out)
    assert key not in out.getvalue()


def test_the_shape_scan_catches_a_key_it_was_never_told_about(tmp_path: Path) -> None:
    """The only check that does not depend on knowing the value, and so the only one that
    can catch a second credential someone else adds later."""
    (tmp_path / "notes.md").write_text("key: AIza" + "a" * 35, encoding="utf-8")
    out = io.StringIO()
    assert keyscan.check_key_shapes(tmp_path, out) is False
    assert "notes.md" in out.getvalue()


def test_the_shape_scan_does_not_flag_ordinary_text(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("the sclera is the white of the eye", encoding="utf-8")
    assert keyscan.check_key_shapes(tmp_path, io.StringIO()) is True


def test_env_is_never_scanned_for_the_literal_value(tmp_path: Path) -> None:
    """`.env` is where the key legitimately lives. Flagging it would make the scan cry wolf
    on every run and train someone to ignore it."""
    (tmp_path / ".env").write_text("AAKAR_API_KEY=PLANTED", encoding="utf-8")
    assert keyscan.check_working_tree(tmp_path, "PLANTED", io.StringIO()) is True
