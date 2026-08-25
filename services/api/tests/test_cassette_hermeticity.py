"""Item 4 — replay mode must fail loudly on a miss, never fall through to a live call.

Rule 7 and D8 put every model call behind the cassette and run all tests and CI in
`replay`. The failure that would matter is silent: a cassette miss that quietly reaches a
real API would spend money from a test run and would look like a pass. These tests assert
the specific exception type, and — the part that actually proves hermeticity — that the
inner provider is never touched even when one is available to be touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aakar.providers import (
    Cassette,
    CassetteMiss,
    CassetteProvider,
    ChatRequest,
    EmbedRequest,
    EmbedResponse,
    StubProvider,
    VlmRequest,
)
from aakar.providers.base import ChatResponse


class SpyProvider:
    """Records whether it was reached. Any non-zero count in replay is a fallthrough."""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.vlm_calls = 0
        self.embed_calls = 0
        self._inner = StubProvider()

    @property
    def total(self) -> int:
        return self.chat_calls + self.vlm_calls + self.embed_calls

    def chat(self, req: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return self._inner.chat(req)

    def vlm(self, req: VlmRequest) -> ChatResponse:
        self.vlm_calls += 1
        return self._inner.vlm(req)

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        self.embed_calls += 1
        return self._inner.embed(req)


CHAT = ChatRequest(model="m", system="s", prompt="never recorded")
VLM = VlmRequest(model="m", system="s", prompt="never recorded", images=(b"\x89PNG-x",))
EMBED = EmbedRequest(model="e", texts=("never recorded",))


def test_replay_miss_raises_cassette_miss_for_chat(tmp_path: Path) -> None:
    provider = CassetteProvider(None, Cassette(tmp_path), "replay")
    with pytest.raises(CassetteMiss):
        provider.chat(CHAT)


def test_replay_miss_raises_cassette_miss_for_vlm(tmp_path: Path) -> None:
    provider = CassetteProvider(None, Cassette(tmp_path), "replay")
    with pytest.raises(CassetteMiss):
        provider.vlm(VLM)


def test_replay_miss_raises_cassette_miss_for_embeddings(tmp_path: Path) -> None:
    provider = CassetteProvider(None, Cassette(tmp_path), "replay")
    with pytest.raises(CassetteMiss):
        provider.embed(EMBED)


def test_replay_miss_never_reaches_an_available_provider(tmp_path: Path) -> None:
    """The hermeticity proof.

    Handing replay a perfectly usable inner provider and then missing the cassette is the
    scenario where a fallthrough would actually cost money. The exception is necessary but
    not sufficient — the call count is what shows nothing was invoked before it raised.
    """
    spy = SpyProvider()
    provider = CassetteProvider(spy, Cassette(tmp_path), "replay")

    calls = (
        lambda: provider.chat(CHAT),
        lambda: provider.vlm(VLM),
        lambda: provider.embed(EMBED),
    )
    for call in calls:
        with pytest.raises(CassetteMiss):
            call()

    assert spy.total == 0, f"replay reached the live provider {spy.total} time(s)"


def test_cassette_miss_message_names_the_fix(tmp_path: Path) -> None:
    """A miss is usually a drifted request, not a missing recording. Say which."""
    provider = CassetteProvider(None, Cassette(tmp_path), "replay")
    with pytest.raises(CassetteMiss) as raised:
        provider.chat(CHAT)
    message = str(raised.value)
    assert "AAKAR_PROVIDER_MODE=record" in message
    assert "drifted" in message


def test_a_hit_still_works_so_the_miss_test_is_not_vacuous(tmp_path: Path) -> None:
    """Guards the guard: prove replay can succeed, or the tests above prove nothing."""
    cassette = Cassette(tmp_path)
    recorded = CassetteProvider(StubProvider(), cassette, "record").chat(CHAT)

    spy = SpyProvider()
    replayed = CassetteProvider(spy, cassette, "replay").chat(CHAT)

    assert replayed.text == recorded.text
    assert spy.total == 0, "replay served a hit but still called the provider"
