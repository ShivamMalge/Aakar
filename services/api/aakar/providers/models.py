"""Model-pin validation (D-045).

**The failure this exists to prevent, stated plainly:** every model in the config was
pinned, and two of the three pins named models the provider had already shut down.
Nothing caught it, because nothing had ever called them — every test ran in replay against
a stub or a local embedder. The first real call would have been the first 404, in
production, on a student's upload.

Pinning protects against *drift*. It does nothing about a pin to something that no longer
exists, and the two failures look identical from inside a replay-mode test suite.

## Two layers, because they catch different things

1. **`RETIRED_MODELS`** — a local registry with shutdown dates, checked in **every mode,
   with no network**. This is the layer that would have caught the actual failure, and it
   works in CI where there is no key. It needs maintenance, and that is the point: a
   retirement is a fact about the world that someone has to write down.

2. **A live resolution check** — in `live`/`record` mode, actually ask the provider whether
   the model resolves. It catches anything the registry has not heard about yet, which is
   every retirement between one maintenance pass and the next.

Neither alone is enough. The registry cannot know about a retirement nobody recorded; the
live check cannot run in the mode that all the tests use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class Retirement:
    replacement: str
    shutdown: date
    note: str = ""


#: Known-retired model ids, from the provider's own deprecation page.
#:
#: Verified 2026-08-30 against https://ai.google.dev/gemini-api/docs/deprecations.
#: Dates there are the *earliest possible* retirement, so a model at or past its date is
#: treated as gone rather than probably-fine.
RETIRED_MODELS: dict[str, Retirement] = {
    "text-embedding-004": Retirement(
        replacement="gemini-embedding-001",
        shutdown=date(2026, 1, 14),
        note="was Aakar's pinned embedding model until D-043 was amended",
    ),
    "embedding-001": Retirement(replacement="gemini-embedding-001", shutdown=date(2025, 10, 30)),
    "gemini-2.0-flash": Retirement(
        replacement="gemini-3.6-flash",
        shutdown=date(2026, 6, 1),
        note="was Aakar's pinned generation AND VLM model until D-045",
    ),
    "gemini-2.0-flash-001": Retirement(replacement="gemini-3.6-flash", shutdown=date(2026, 6, 1)),
    "gemini-2.0-flash-lite": Retirement(
        replacement="gemini-3.1-flash-lite", shutdown=date(2026, 6, 1)
    ),
    "gemini-2.0-flash-lite-001": Retirement(
        replacement="gemini-3.1-flash-lite", shutdown=date(2026, 6, 1)
    ),
}


class RetiredModel(RuntimeError):
    """A configured model is past its shutdown date. Raised at boot, never at first use."""


def check_model(model: str, *, label: str, today: date | None = None) -> None:
    """Refuse a model the provider has retired.

    `label` names the setting, because "gemini-2.0-flash is retired" is far less useful
    than knowing it is the *VLM* pin that is retired when three settings could hold it.
    """
    retirement = RETIRED_MODELS.get(model)
    if retirement is None:
        return
    now = today or datetime.now(UTC).date()
    if now < retirement.shutdown:
        return
    detail = f" ({retirement.note})" if retirement.note else ""
    raise RetiredModel(
        f"{label} is set to {model!r}, which the provider shut down on "
        f"{retirement.shutdown.isoformat()}{detail}. Use {retirement.replacement!r}. "
        "A pinned model that no longer exists fails on first real call, not at boot — "
        "which is why this check exists (D-045)."
    )


def check_configured_models(models: dict[str, str], *, today: date | None = None) -> list[str]:
    """Check every pin. Returns the labels checked, so a caller can log what it verified.

    Raises on the first retirement rather than collecting them: a boot that continues past
    one dead pin to report a second has already failed.
    """
    for label, model in models.items():
        check_model(model, label=label, today=today)
    return sorted(models)


#: Where the provider lists the models a key can actually reach.
LIST_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def resolve_live(api_key: str, models: dict[str, str], *, timeout: float = 10.0) -> dict[str, bool]:
    """Ask the provider which configured models actually exist.

    Layer 2. Only meaningful in ``live``/``record`` mode, since it needs a key — which is
    exactly why layer 1 exists: every test in this project runs in ``replay``, so a check
    that needed a key would never have run and never have caught the retired pins.

    Returns ``{label: resolved}``. Raises only if the listing itself fails, because "the
    provider is unreachable" and "your model does not exist" are different problems, and
    conflating them would make a network blip look like a bad pin.
    """
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        f"{LIST_MODELS_URL}?key={api_key}&pageSize=1000",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - network, TLS, JSON: all "cannot tell"
        raise RuntimeError(f"could not list models at the provider: {exc}") from exc

    # Ids come back as "models/gemini-3.6-flash"; compare on the bare name.
    available = {
        str(entry.get("name", "")).removeprefix("models/") for entry in payload.get("models", [])
    }
    return {label: model in available for label, model in models.items()}


def assert_live_models(api_key: str, models: dict[str, str]) -> None:
    """Fail loudly when a configured model does not resolve at the provider."""
    resolved = resolve_live(api_key, models)
    missing = {label: models[label] for label, ok in resolved.items() if not ok}
    if missing:
        listed = ", ".join(f"{label}={model!r}" for label, model in sorted(missing.items()))
        raise RetiredModel(
            f"the provider does not list these configured models: {listed}. "
            "They may have been retired since RETIRED_MODELS was last updated (D-045)."
        )
