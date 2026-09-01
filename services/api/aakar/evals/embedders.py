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
    build: Callable[[], EmbedFn]

    def __call__(self, text: str) -> Sequence[float]:
        return self.build()(text)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model} @ {self.dimensions}d)"


def _local() -> EmbedFn:
    return lambda text: local_embed(text, DEFAULT_DIMENSIONS)


def _gemini() -> EmbedFn:
    """The shipping embedder.

    **There is no live provider in the repository yet** — 2D.2 builds it, because it needs a
    key. This row exists now anyway, and raises rather than silently falling back to
    ``local``: a fallback would let every harness keep printing numbers while quietly
    measuring the stub, which is precisely the confusion the split into 2D.1 and 2D.2 was
    meant to prevent.

    Wiring it up is one line here plus `AAKAR_EVAL_EMBEDDER=gemini`. No harness changes.
    """
    raise NotImplementedError(
        "the live embedding provider lands in 2D.2 (it needs an API key). Build it, then "
        "return Embedder(<provider>, EmbeddingConfig.from_env()).embed_query from here."
    )


def provider_embedder(provider: Provider) -> EmbedFn:
    """Adapt any `Provider` into the single-text callable every harness takes.

    The seam 2D.2 needs: wiring a real provider in touches this line and the registry row
    below, and nothing that consumes them.
    """
    return Embedder(provider, EmbeddingConfig.from_env()).embed_query


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
