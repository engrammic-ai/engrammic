"""Cross-encoder reranking via LiteLLM."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import litellm
import structlog

logger = structlog.get_logger(__name__)

MAX_RETRIES = 2
RETRY_DELAY = 0.1


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
        vertex_project: str | None = None,
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds
        self._vertex_project = vertex_project

    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query."""
        if not documents:
            return []

        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents ({len(documents)}) and node_ids ({len(node_ids)}) must have same length"
            )

        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs: dict[str, object] = {
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                    "timeout": self._timeout,
                }
                if self._vertex_project and self._model.startswith("vertex_ai/"):
                    kwargs["vertex_ai_project"] = self._vertex_project
                response = await litellm.arerank(**kwargs)
                return [
                    RerankResult(
                        node_id=node_ids[r["index"]],
                        score=r["relevance_score"],
                        original_rank=r["index"],
                    )
                    for r in response.results
                ]
            except Exception as e:
                if attempt < MAX_RETRIES:
                    logger.debug("reranking_retry", attempt=attempt + 1, error=str(e))
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                logger.warning("reranking_failed", error=str(e), model=self._model)
                raise
        raise RuntimeError("rerank: unreachable")
