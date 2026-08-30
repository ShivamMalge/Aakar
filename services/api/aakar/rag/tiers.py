"""Model tiering (2B.8).

Two tiers, because the two kinds of call have opposite economics:

* **generation** — SceneSpec emission and the VLM critic. Runs once per topic, forever
  (D4), and amortises across every reader of that topic. A frontier model here is bought
  once.
* **answer** — QA from retrieved chunks. Runs per user, per question, and never stops.

**Only the answer tier scales with users.** That is the whole reason for the split, and it
is why the ledger records the tier: a cost report that cannot separate the two cannot tell
you whether a rising bill means more topics or more readers, which are entirely different
problems.

The tier is chosen at the call site, not inferred from the model name — a deployment that
happens to configure the same model for both must still produce a truthful split.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from aakar.config import DEFAULT_EMBED_MODEL, DEFAULT_MODEL, DEFAULT_VLM_MODEL


class Tier(StrEnum):
    GENERATION = "generation"
    ANSWER = "answer"


@dataclass(frozen=True)
class TierConfig:
    """Model per tier, from env. Defaults keep replay-mode tests honest without a key."""

    generation_model: str
    answer_model: str
    vlm_model: str
    embed_model: str

    def model_for(self, tier: Tier) -> str:
        return self.generation_model if tier is Tier.GENERATION else self.answer_model

    @staticmethod
    def from_env() -> TierConfig:
        # AAKAR_MODEL stays the generation default so existing config keeps working; the
        # answer tier falls back to it rather than silently choosing something cheaper,
        # because a silent downgrade of answer quality is worse than an obvious bill.
        generation = os.environ.get("AAKAR_MODEL", DEFAULT_MODEL)
        return TierConfig(
            generation_model=generation,
            answer_model=os.environ.get("AAKAR_ANSWER_MODEL", generation),
            vlm_model=os.environ.get("AAKAR_VLM_MODEL", DEFAULT_VLM_MODEL),
            embed_model=os.environ.get("AAKAR_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        )
