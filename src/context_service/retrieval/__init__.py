"""Retrieval module - fusion and channel orchestration."""

from context_service.retrieval.cross_encoder import CrossEncoderReranker, CrossEncoderResult
from context_service.retrieval.fusion import (
    ChannelResult,
    FusedResult,
    FusionRetriever,
)

__all__ = [
    "ChannelResult",
    "CrossEncoderReranker",
    "CrossEncoderResult",
    "FusedResult",
    "FusionRetriever",
]
