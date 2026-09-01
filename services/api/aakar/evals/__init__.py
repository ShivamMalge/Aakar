"""Evaluation harnesses (2D.1).

Separate from `aakar.rag` on purpose: nothing here is on a request path. These modules
measure the RAG stack, and a measurement that imports into production is a measurement
that can be quietly satisfied by production changing to suit it.

Two rules hold across everything in this package:

* **Counts, not scores.** A score hides which failure happened, and the three citation
  failures need three different fixes.
* **Provenance on every number.** Every result carries the embedder that produced it and
  whether the golden labels behind it were human-verified. A number without those two
  facts attached gets repeated later without them (D-041).
"""

from .embedders import EMBEDDERS, NamedEmbedder, embedder_from_env, resolve_embedder
from .faithfulness import (
    FaithfulnessReport,
    SentenceVerdict,
    evaluate_answer,
    format_report,
    supports,
)
from .golden import GoldenQuestion, GoldenSet, load_golden_set
from .thresholds import calibrate_relevance_floor, format_floor_table

__all__ = [
    "EMBEDDERS",
    "FaithfulnessReport",
    "GoldenQuestion",
    "GoldenSet",
    "NamedEmbedder",
    "SentenceVerdict",
    "calibrate_relevance_floor",
    "embedder_from_env",
    "evaluate_answer",
    "format_floor_table",
    "format_report",
    "load_golden_set",
    "resolve_embedder",
    "supports",
]
