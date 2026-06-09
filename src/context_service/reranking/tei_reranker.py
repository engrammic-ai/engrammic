"""Cross-encoder reranking via TEI /rerank endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
import structlog

from .reranker import RerankResult

logger = structlog.get_logger(__name__)

MAX_RETRIES = 2
BASE_RETRY_DELAY = 0.1


class TEIRerankerError(Exception):
    """Raised when TEI reranking fails after all retries."""


@dataclass
class TEIReranker:
    """Cross-encoder reranking via Text Embeddings Inference /rerank endpoint."""

    base_url: str = "http://localhost:8082"
    timeout_seconds: float = 2.0
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query via TEI.

        Args:
            query: Search query.
            documents: List of document texts.
            node_ids: Corresponding node IDs.
            top_k: Maximum number of results to return.

        Returns:
            Top-k results sorted by score descending.
        """
        if not documents:
            return []

        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents ({len(documents)}) and node_ids ({len(node_ids)}) must have same length"
            )

        payload = {"query": query, "texts": documents}

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.post("/rerank", json=payload)
                response.raise_for_status()
                data: list[dict[str, float | int]] = response.json()
                results = [
                    RerankResult(
                        node_id=node_ids[int(item["index"])],
                        score=float(item["score"]),
                        original_rank=int(item["index"]),
                    )
                    for item in data
                ]
                return results[:top_k]
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    delay = BASE_RETRY_DELAY * (2**attempt)
                    logger.debug(
                        "tei_reranker_retry",
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning("tei_reranker_failed", error=str(e), base_url=self.base_url)

        raise TEIRerankerError(
            f"TEI reranking failed after {MAX_RETRIES + 1} attempts"
        ) from last_exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> TEIReranker:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
