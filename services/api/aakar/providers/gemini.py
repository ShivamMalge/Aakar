"""The live Gemini backend (2D.2). The only code in this project that talks to a model API.

Everything else goes through `Provider`, so this class is the single place a real request is
built and a real dollar is spent (Rule 7, D8). It is constructed **only** in `live`/`record`
mode; `replay` never builds it, which is what lets CI run with no key.

## Pricing is a list price, and the ledger says so

`PRICING` holds the provider's published **paid-tier** rates. If the key is on the free
tier the true charge is $0, so `Usage.usd` is an **upper bound**, never an understatement.
That is the safe direction for a guard that stops a run: erring high trips the budget early,
erring low re-opens the hole D8 exists to close. An unpriced model raises rather than
recording `usd=0.0` — a silent zero would turn the ledger from a record into a decoration.

## Embedding token counts are estimated, and are labelled as such

`batchEmbedContents` returns no `usageMetadata`. Calling `countTokens` for every text would
double the request count against a free-tier per-minute limit to price a call that costs
about two hundredths of a cent. So embedding tokens use the standard four-characters-per-
token approximation, which is an estimate and is named as one here rather than passed off
as measured. Chat and VLM use the provider's own counts.

## Rate limits are backed off, never worked around

Free-tier keys have per-minute and per-day request limits. A 429 is retried with exponential
backoff, honouring the provider's own `retryDelay` when it sends one. It is never handled by
sampling less input: a sweep that quietly shrinks under rate pressure reports a number about
a different experiment than the one that was asked for.
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .base import ChatRequest, ChatResponse, EmbedRequest, EmbedResponse, Usage, VlmRequest

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class Price:
    """USD per million tokens, paid tier."""

    input_per_m: float
    output_per_m: float = 0.0


#: Published paid-tier pricing, read from ai.google.dev/gemini-api/docs/pricing on
#: 2026-09-01. Gemini 3.6 Flash is listed at "$0.75 through December 31, 2026. $1.50
#: starting January 1, 2027" for input and "$3.75 ... $7.50" for output; the pre-2027 rate
#: is used here and the step-up is a dated fact someone must revisit, exactly like a model
#: retirement (D-045).
PRICING: dict[str, Price] = {
    "gemini-3.6-flash": Price(input_per_m=0.75, output_per_m=3.75),
    "gemini-embedding-001": Price(input_per_m=0.15),
}

#: 2027-01-01 doubles both generation rates. Recorded next to the table it invalidates.
PRICING_VALID_THROUGH = "2026-12-31"

#: Characters per token. The usual rule of thumb, used only where the provider returns no
#: count of its own — see the module docstring.
CHARS_PER_TOKEN = 4

MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 2.0

#: Seconds to wait between requests. A free-tier key enforces its per-minute limit partly
#: by dropping the connection rather than answering 429, which surfaces as an SSL EOF and
#: looks like a network fault. Pacing is cheaper than discovering that eight times.
PACE_SECONDS = float(os.environ.get("AAKAR_PACE_SECONDS", "0.7"))
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class UnpricedModel(RuntimeError):
    """A live call was made against a model with no published rate recorded."""


class ProviderError(RuntimeError):
    """The provider refused or failed. Never carries the key."""


def price_for(model: str) -> Price:
    try:
        return PRICING[model]
    except KeyError:
        raise UnpricedModel(
            f"no price recorded for {model!r}. Add it to PRICING from the provider's "
            "pricing page rather than letting the ledger record $0.00 for a real call."
        ) from None


def usd_for(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = price_for(model)
    return (prompt_tokens * price.input_per_m + completion_tokens * price.output_per_m) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Only for calls the provider does not count. Never presented as measured."""
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


class GeminiProvider:
    """`Provider` over the Gemini REST API.

    `api_key` is read from the environment and never stored anywhere but this instance —
    it is not logged, not put in an exception message, and cannot reach a cassette, which
    records only the response payload (see `cassette.py`).
    """

    def __init__(self, api_key: str | None = None, *, timeout: float = 60.0) -> None:
        key = api_key or os.environ.get("AAKAR_API_KEY", "")
        if not key:
            raise ProviderError(
                "AAKAR_API_KEY is not set. The live provider is only constructed in "
                "live/record mode; replay never needs it."
            )
        self._key = key
        self._timeout = timeout

    # ------------------------------------------------------------------ transport

    def _post(self, path: str, body: dict[str, object]) -> dict[str, Any]:
        """POST with backoff. The key travels in the query string and never in a message.

        Returns `dict[str, Any]`: the response is JSON of the provider's shape, not ours,
        and every field is read defensively below. Typing it as `object` would only move
        the same runtime uncertainty into a wall of casts.
        """
        url = f"{BASE_URL}/{path}?key={self._key}"
        payload = json.dumps(body).encode()
        if PACE_SECONDS:
            time.sleep(PACE_SECONDS)
        last: str = "no attempt was made"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            request = urllib.request.Request(  # noqa: S310 - fixed https host
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    parsed = json.load(response)
                    assert isinstance(parsed, dict)
                    return parsed
            except urllib.error.HTTPError as exc:
                detail = self._redact(exc.read().decode("utf-8", "replace"))
                if exc.code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                    raise ProviderError(f"HTTP {exc.code} from {path}: {detail[:600]}") from None
                delay = self._retry_delay(detail, attempt)
                last = f"HTTP {exc.code}"
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise ProviderError(f"{path} unreachable: {self._redact(str(exc))}") from None
                last = "transport"
                time.sleep(self._backoff(attempt))

        raise ProviderError(f"{path} failed after {MAX_ATTEMPTS} attempts ({last})")

    def _backoff(self, attempt: int) -> float:
        """Exponential with jitter. Jitter matters: a sweep retries in lockstep otherwise,
        and re-hits the per-minute limit at exactly the same instant every time."""
        jitter: float = random.uniform(0, 1)  # noqa: S311 - timing, not security
        return BACKOFF_BASE_SECONDS * (2.0 ** (attempt - 1)) + jitter

    def _retry_delay(self, detail: str, attempt: int) -> float:
        """Prefer the provider's own `retryDelay` — it knows when the window reopens."""
        try:
            payload: dict[str, Any] = json.loads(detail)
            for item in payload.get("error", {}).get("details", []):
                raw = str(item.get("retryDelay", ""))
                if raw.endswith("s") and raw[:-1].replace(".", "", 1).isdigit():
                    return float(raw[:-1]) + 1.0
        except (ValueError, AttributeError):
            pass
        return self._backoff(attempt)

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "<AAKAR_API_KEY>")

    # ------------------------------------------------------------------ the interface

    def _generate(
        self, model: str, system: str, parts: list[dict[str, object]], temp: float, max_tokens: int
    ) -> ChatResponse:
        body: dict[str, object] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temp, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        payload = self._post(f"models/{model}:generateContent", body)
        candidates = payload.get("candidates") or []
        text = ""
        if candidates:
            content = candidates[0].get("content") or {}
            text = "".join(
                str(part.get("text", "")) for part in content.get("parts", []) if "text" in part
            )

        meta = payload.get("usageMetadata") or {}
        prompt_tokens = int(meta.get("promptTokenCount", 0))
        completion_tokens = int(meta.get("candidatesTokenCount", 0))
        return ChatResponse(
            text=text,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd=usd_for(model, prompt_tokens, completion_tokens),
            ),
        )

    def chat(self, req: ChatRequest) -> ChatResponse:
        return self._generate(
            req.model, req.system, [{"text": req.prompt}], req.temperature, req.max_tokens
        )

    def vlm(self, req: VlmRequest) -> ChatResponse:
        parts: list[dict[str, object]] = [{"text": req.prompt}]
        for image in req.images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(image).decode(),
                    }
                }
            )
        return self._generate(req.model, req.system, parts, req.temperature, req.max_tokens)

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        """Batch embed. Dimensionality and task type are both sent — D-043 fixes the first,
        and the provider embeds documents and queries asymmetrically, so omitting the second
        would throw away half of what the model does."""
        requests: list[dict[str, object]] = []
        for text in req.texts:
            entry: dict[str, object] = {
                "model": f"models/{req.model}",
                "content": {"parts": [{"text": text}]},
            }
            if req.task_type:
                entry["taskType"] = req.task_type
            if req.output_dimensionality:
                entry["outputDimensionality"] = req.output_dimensionality
            requests.append(entry)

        payload = self._post(f"models/{req.model}:batchEmbedContents", {"requests": requests})
        raw = payload.get("embeddings") or []
        vectors = tuple(tuple(float(v) for v in item.get("values", [])) for item in raw)
        if len(vectors) != len(req.texts):
            raise ProviderError(
                f"asked for {len(req.texts)} embeddings, got {len(vectors)}. A short batch "
                "would silently misalign every vector with its chunk."
            )

        # Estimated, not measured — batchEmbedContents returns no usageMetadata.
        tokens = sum(estimate_tokens(t) for t in req.texts)
        return EmbedResponse(
            vectors=vectors,
            usage=Usage(prompt_tokens=tokens, usd=usd_for(req.model, tokens, 0)),
        )
