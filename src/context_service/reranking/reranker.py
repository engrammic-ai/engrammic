"""Cross-encoder reranking via LiteLLM."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RerankResult:
    """Result from reranking operation."""

    node_id: str
    score: float
    original_rank: int


class LiteLLMReranker:
    """Cross-encoder reranker backed by LiteLLM. Implemented in Task 2."""
