"""Named embedders for the eval harnesses (2D.1d).

Every threshold in this project — the cache similarity threshold (D-041) and the relevance
floor (2C.3) — is a property of **the embedder that produced the vectors**, not of the
system. A number measured on the local lexical stub is not a conservative version of the
real number; it is a number about a different function. Swapping embedders must therefore
be configuration, and every result must carry the embedder's name so a provisional number
cannot be quoted later as if it were final.

That is what `NamedEmbedder.calibrating` encodes: a *false* value means "this embedder
cannot produce a shippable threshold", and the harnesses stamp PROVISIONAL on their output
rather than trusting the reader to remember.

The registry is small on purpose. `local` runs with no key and proves the harness; `gemini`
is the one that ships. Adding a third means adding a row here and setting one environment
variable — no harness changes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from aakar.providers import Provider
from aakar.rag.embedding import (
    DEFAULT_DIMENSIONS,
    DEFAULT_MODEL,
    Embedder,
    EmbeddingConfig,
    local_embed,
)

#: What every harness accepts: text in, vector out.
EmbedFn = Callable[[str], Sequence[float]]


@dataclass(frozen=True)
class Embedders:
    """Query and document embedders, kept apart because the provider is asymmetric.

    `gemini-embedding-001` embeds a passage and a question differently — that is what
    `RETRIEVAL_DOCUMENT` and `RETRIEVAL_QUERY` are for, and using one for both throws away
    half of what the model does. A single callable made that mistake invisible: the golden
    harness embedded **chunk text through the query path**, which the local stub ignores
    (it has no task type) and the real embedder does not. The bug was undetectable on the
    embedder it was developed against, which is the whole reason for the 2D.1/2D.2 split.
    """

    query: EmbedFn
    document: EmbedFn


ENV_VAR = "AAKAR_EVAL_EMBEDDER"


@dataclass(frozen=True)
class NamedEmbedder:
    """An embedder plus the two facts a result must carry to be re-readable later."""

    name: str
    #: Model id, or a description for anything not from a provider.
    model: str
    dimensions: int
    #: False when a threshold measured on this embedder must not be shipped.
    calibrating: bool
    #: Why, in one line — printed with the result so the caveat travels with the number.
    caveat: str
    build: Callable[[], Embedders]

    def __call__(self, text: str) -> Sequence[float]:
        """Convenience for a query. Documents must go through `build().document`."""
        return self.build().query(text)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model} @ {self.dimensions}d)"


def _local() -> Embedders:
    """The stub has no task type, so both sides are the same function — stated here rather
    than left to look like an oversight."""
    fn: EmbedFn = lambda text: local_embed(text, DEFAULT_DIMENSIONS)  # noqa: E731
    return Embedders(query=fn, document=fn)


def _gemini() -> Embedders:
    """The shipping embedder, **through the cassette** (D8, Rule 7).

    Mode comes from `AAKAR_PROVIDER_MODE`, so the same registry row serves both halves of
    2D.2: `record` builds the live provider and writes cassettes, `replay` reads them and
    never constructs a provider or reads a key. That is what makes "everything downstream
    stays replay, CI never needs the key" true rather than aspirational — the alternative,
    a second `gemini-replay` row, would be two code paths that could drift apart while both
    claiming to measure the same embedder.

    Built lazily: importing the registry must not construct a provider or read a key, or
    every replay test would need one merely to enumerate the methods.
    """
    from aakar.config import Settings  # noqa: PLC0415 - deliberately lazy
    from aakar.providers import Cassette, CassetteProvider, GeminiProvider  # noqa: PLC0415

    settings = Settings.from_env()
    mode = settings.provider_mode
    inner = GeminiProvider() if mode != "replay" else None
    return provider_embedder(CassetteProvider(inner, Cassette(settings.cassette_dir), mode))


def provider_embedder(provider: Provider) -> Embedders:
    """Adapt any `Provider` into the query/document pair every harness takes.

    The seam 2D.2 needs: wiring a real provider in touches this line and the registry row
    below, and nothing that consumes them.
    """
    embedder = Embedder(provider, EmbeddingConfig.from_env())
    return Embedders(
        query=embedder.embed_query,
        # One text per call, matching what the harness sends at replay time — a batch here
        # would record under a different request hash and never be replayed.
        document=lambda text: embedder.embed([text])[0],
    )


EMBEDDERS: dict[str, NamedEmbedder] = {
    "local": NamedEmbedder(
        name="local",
        model="hashed bag-of-words + character trigrams",
        dimensions=DEFAULT_DIMENSIONS,
        calibrating=False,
        caveat=(
            "lexical, not semantic. Similarity here measures word overlap, so a threshold "
            "measured on it describes string matching and not meaning (D-041)."
        ),
        build=_local,
    ),
    "gemini": NamedEmbedder(
        name="gemini",
        model=DEFAULT_MODEL,
        dimensions=DEFAULT_DIMENSIONS,
        calibrating=True,
        caveat="",
        build=_gemini,
    ),
}


def resolve_embedder(name: str) -> NamedEmbedder:
    try:
        return EMBEDDERS[name]
    except KeyError:
        known = ", ".join(sorted(EMBEDDERS))
        raise KeyError(f"unknown eval embedder {name!r}; known: {known}") from None


def embedder_from_env(default: str = "local") -> NamedEmbedder:
    """Pick the embedder from the environment.

    Defaults to ``local`` so the harnesses run in CI with no key and no spend. The default
    is the *safe* one rather than the accurate one, because the failure mode of the
    accurate default is a surprise bill on someone's first `pytest`, while the failure mode
    of this one is a number stamped PROVISIONAL — which is a caption, not a defect.
    """
    return resolve_embedder(os.environ.get(ENV_VAR, default))
