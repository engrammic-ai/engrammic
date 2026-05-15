"""Cross-encoder reranking via LiteLLM."""

from __future__ import annotations

from dataclasses import dataclass

import litellm
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RerankResult:
    """Result from reranking operation."""

    node_id: str
    score: float
    original_rank: int


class LiteLLMReranker:
    """Cross-encoder reranking via LiteLLM."""

    def __init__(
        self,
        model: str = "vertex_ai/semantic-ranker-default@latest",
        timeout_seconds: float = 2.0,
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds

    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query.

        Args:
            query: The search query.
            documents: Document contents to rerank.
            node_ids: Corresponding node IDs (preserved through reranking).
            top_k: Maximum results to return.

        Returns:
            Top-K results sorted by relevance score.
        """
        if not documents:
            return []

        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents ({len(documents)}) and node_ids ({len(node_ids)}) must have same length"
            )

        try:
            response = await litellm.arerank(
                model=self._model,
                query=query,
                documents=documents,
                top_n=top_k,
                timeout=self._timeout,
            )
            return [
                RerankResult(
                    node_id=node_ids[r["index"]],
                    score=r["relevance_score"],
                    original_rank=r["index"],
                )
                for r in response.results
            ]
        except Exception as e:
            logger.warning("reranking_failed", error=str(e), model=self._model)
            # Fallback: return original order with decaying scores
            return [
                RerankResult(node_id=nid, score=1.0 - i * 0.01, original_rank=i)
                for i, nid in enumerate(node_ids[:top_k])
            ]
