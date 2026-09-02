"""One generation, classified (3B.1, 3B.2, 3B.4).

`classify` answers the three questions the gate asks about every generation, in order,
without repair and without retry:

1. **Did it parse as JSON at all?**
2. **Is it schema-valid on the first attempt?** — `SceneSpec.model_validate` alone.
3. **Is it referentially valid?** — unique ids, parents resolve, no cycles — reported
   separately, because a document can hold the schema and still reference a parent that
   does not exist, and the two failures need different fixes.

Then `verify_provenance` re-checks every `chunk_ids` claim with the whole-word matcher
provenance resolution uses (D-030). Three counts per generation:

* **zero-provenance parts** — `chunk_ids == []`. Legal, expected, and the gate requires
  that they actually occur somewhere: a generator that never emits one has found something
  to cite for everything, which is the failure 3B.2 names.
* **fabricated citations** — a cited chunk that does not name the part. The lie this whole
  project exists to make detectable.
* **unknown chunk ids** — a citation to a chunk that is not in the chapter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from aakar.providers import ChatRequest, Provider, Usage
from aakar.scenespec import validate_referential
from aakar.scenespec.generated import SceneSpec
from aakar.structures.verify import mentions

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class GenerationOutcome:
    raw: str
    document: dict[str, Any] | None
    parse_error: str | None
    schema_valid: bool
    schema_errors: tuple[str, ...]
    referential_valid: bool
    referential_errors: tuple[str, ...]
    part_count: int
    zero_provenance: tuple[str, ...] = ()
    fabricated: tuple[tuple[str, str], ...] = ()
    unknown_chunks: tuple[tuple[str, str], ...] = ()
    usage: Usage = field(default_factory=Usage)

    @property
    def valid(self) -> bool:
        """Both checks, which is what `parse_scene_spec` requires before a spec is stored."""
        return self.schema_valid and self.referential_valid


def parse_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"not JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "JSON is not an object"
    return payload, None


def classify(text: str) -> GenerationOutcome:
    document, error = parse_json(text)
    if document is None:
        return GenerationOutcome(
            raw=text,
            document=None,
            parse_error=error,
            schema_valid=False,
            schema_errors=(),
            referential_valid=False,
            referential_errors=(),
            part_count=0,
        )

    schema_errors: tuple[str, ...] = ()
    try:
        SceneSpec.model_validate(document)
        schema_valid = True
    except ValidationError as exc:
        schema_valid = False
        schema_errors = tuple(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:12]
        )

    raw_parts = document.get("parts")
    parts: list[Any] = raw_parts if isinstance(raw_parts, list) else []
    referential = validate_referential(document) if parts else []
    return GenerationOutcome(
        raw=text,
        document=document,
        parse_error=None,
        schema_valid=schema_valid,
        schema_errors=schema_errors,
        referential_valid=not referential,
        referential_errors=tuple(f"{e.path}: {e.code}" for e in referential),
        part_count=len(parts),
    )


def verify_provenance(
    outcome: GenerationOutcome, chunks: Mapping[str, tuple[str, str]]
) -> GenerationOutcome:
    """Re-check every citation. Mutates and returns the outcome for chaining.

    A part "is named" by a chunk when the chunk contains the part's name or any alias,
    whole-word — the same test provenance resolution applies later (D-030), so a claim this
    passes here is one the product would credit.
    """
    if outcome.document is None:
        return outcome
    texts = {cid: text for cid, (_p, text) in chunks.items()}
    zero: list[str] = []
    fabricated: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []
    for part in outcome.document.get("parts", []):
        if not isinstance(part, dict):
            continue
        pid = str(part.get("id", "?"))
        forms = [str(part.get("name", ""))] + [str(a) for a in part.get("aliases", []) or []]
        prov = part.get("provenance") or {}
        ids = prov.get("chunk_ids") if isinstance(prov, dict) else None
        if not ids:
            zero.append(pid)
            continue
        for cid in ids:
            cid = str(cid)
            if cid not in texts:
                unknown.append((pid, cid))
            elif not mentions(texts[cid], forms):
                fabricated.append((pid, cid))
    outcome.zero_provenance = tuple(zero)
    outcome.fabricated = tuple(fabricated)
    outcome.unknown_chunks = tuple(unknown)
    return outcome


def generate(
    provider: Provider,
    *,
    model: str,
    system: str,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 16384,
) -> tuple[str, Usage]:
    """One call. No retry: a failure is a data point about the model (3B.4)."""
    response = provider.chat(
        ChatRequest(
            model=model,
            system=system,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    )
    return response.text, response.usage
