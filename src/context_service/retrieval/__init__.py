"""Retrieval module - fusion and channel orchestration."""

from context_service.retrieval.fusion import (
    ChannelResult,
    FusedResult,
    FusionRetriever,
)
from context_service.retrieval.ppr import PersonalizedPageRank
from context_service.retrieval.temporal import (
    TemporalQuery,
    compute_recency_score,
    parse_temporal_query,
)

__all__ = [
    "ChannelResult",
    "FusedResult",
    "FusionRetriever",
    "PersonalizedPageRank",
    "TemporalQuery",
    "compute_recency_score",
    "parse_temporal_query",
]
