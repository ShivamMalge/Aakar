"""Retrieval, caching and the spend controls around them (Phase 2B)."""

from .ask import Answer, Citation, NotPermitted, ask
from .benchmark import QuestionPair, ThresholdResult, evaluate, format_table, recommend
from .cache import (
    DEFAULT_THRESHOLD,
    CachedAnswer,
    configured_threshold,
    cosine,
    lookup,
    scope_key,
    store,
)
from .degraded import DegradedReason, ServiceState, assess
from .embedding import DEFAULT_DIMENSIONS, Embedder, EmbeddingConfig, local_embed
from .index import COLLECTION, Hit, ensure_collection, search, upsert_chunks
from .provenance_resolve import ResolvedProvenance, combine_sources
from .provenance_resolve import resolve as resolve_provenance
from .quota import OwnerQuota, QuotaExceeded, check_owner_quota, questions_today
from .registration import RegistrationPolicy, account_count, has_capacity, register_or_waitlist
from .retrieval import DEFAULT_FLOOR, Retrieval, part_scope_terms, relevance_floor, retrieve
from .tiers import Tier, TierConfig

__all__ = [
    "COLLECTION",
    "DEFAULT_DIMENSIONS",
    "DEFAULT_FLOOR",
    "Answer",
    "Citation",
    "Embedder",
    "EmbeddingConfig",
    "Hit",
    "NotPermitted",
    "ResolvedProvenance",
    "Retrieval",
    "ask",
    "combine_sources",
    "ensure_collection",
    "local_embed",
    "part_scope_terms",
    "relevance_floor",
    "resolve_provenance",
    "retrieve",
    "search",
    "upsert_chunks",
    "DEFAULT_THRESHOLD",
    "CachedAnswer",
    "QuestionPair",
    "ThresholdResult",
    "DegradedReason",
    "OwnerQuota",
    "QuotaExceeded",
    "RegistrationPolicy",
    "ServiceState",
    "Tier",
    "TierConfig",
    "account_count",
    "assess",
    "check_owner_quota",
    "configured_threshold",
    "cosine",
    "evaluate",
    "format_table",
    "recommend",
    "has_capacity",
    "lookup",
    "questions_today",
    "register_or_waitlist",
    "scope_key",
    "store",
]
