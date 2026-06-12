"""Semantic reranking for improved recall accuracy."""

from context_service.reranking.epistemic_fusion import (
    EpistemicAdjustment,
    apply_epistemic_fusion,
    compute_epistemic_adjustment,
)
from context_service.reranking.factory import get_reranker
from context_service.reranking.quality import (
    LAYER_THRESHOLDS,
    RERANK_SCORE_FLOOR,
    RetrievalQuality,
    apply_threshold_filter,
    classify_quality,
    compute_adaptive_threshold,
    compute_retrieval_quality,
)
from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.query_expander import QueryExpander
from context_service.reranking.reranker import LiteLLMReranker, RerankResult
from context_service.reranking.tei_reranker import TEIReranker, TEIRerankerError

__all__ = [
    "EpistemicAdjustment",
    "LAYER_THRESHOLDS",
    "LiteLLMReranker",
    "QueryExpander",
    "RERANK_SCORE_FLOOR",
    "RerankResult",
    "RetrievalQuality",
    "TEIReranker",
    "TEIRerankerError",
    "apply_epistemic_fusion",
    "apply_threshold_filter",
    "classify_quality",
    "compute_adaptive_threshold",
    "compute_epistemic_adjustment",
    "compute_retrieval_quality",
    "get_reranker",
    "is_hard_query",
]
