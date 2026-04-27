"""Jina v4 embedding service client with retry support."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache
    from context_service.config.settings import Settings

logger = get_logger(__name__)


class JinaEmbeddingError(Exception):
    """Raised when Jina embedding operations fail."""

    pass


class JinaEmbeddingService:
    """Jina v4 embedding client using httpx for async requests."""

    TASK_PASSAGE = "retrieval.passage"
    TASK_QUERY = "retrieval.query"

    def __init__(
        self,
        api_key: str,
        model: str = "jina-embeddings-v4",
        dimensions: int = 1024,
        api_url: str = "https://api.jina.ai/v1/embeddings",
        _embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        """Initialize the Jina embedding service.

        Args:
            api_key: Jina API key.
            model: Jina embedding model name.
            dimensions: Output embedding dimensions.
            api_url: Jina API endpoint URL.
            _embedding_cache: Optional Redis-backed embedding cache.
        """
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._api_url = api_url
        self._client: httpx.AsyncClient | None = None
        self._embedding_cache = _embedding_cache

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        _embedding_cache: EmbeddingCache | None = None,
    ) -> JinaEmbeddingService:
        """Create a JinaEmbeddingService from application settings.

        Args:
            settings: Application settings instance.
            _embedding_cache: Optional Redis-backed embedding cache.

        Returns:
            Configured JinaEmbeddingService.

        Raises:
            ValueError: If Jina API key is not configured.
        """
        if not settings.jina_api_key:
            raise ValueError("JINA_API_KEY is required for embedding service")

        return cls(
            api_key=settings.jina_api_key,
            model=getattr(settings, "jina_model", "jina-embeddings-v4"),
            dimensions=getattr(settings, "jina_dimensions", 1024),
            api_url=getattr(settings, "jina_api_url", "https://api.jina.ai/v1/embeddings"),
            _embedding_cache=_embedding_cache,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with retry transport."""
        if self._client is None:
            transport = httpx.AsyncHTTPTransport(retries=3)
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _request_with_backoff(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        """Make API request with exponential backoff on 429 rate limit."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                response = await client.post(self._api_url, json=payload)
                if response.status_code == 429 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "jina_rate_limited",
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                if 500 <= response.status_code < 600 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "jina_server_error",
                        status_code=response.status_code,
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.RequestError as e:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "jina_request_error",
                        error=str(e),
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        raise JinaEmbeddingError("Max retries exceeded")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            JinaEmbeddingError: If the API request fails.
        """
        if not texts:
            return []

        if self._embedding_cache:
            cached_results: list[list[float] | None] = []
            for text in texts:
                cached_results.append(await self._embedding_cache.get(text, self.TASK_PASSAGE))
            if all(v is not None for v in cached_results):
                return [v for v in cached_results if v is not None]
            miss_indices = [i for i, v in enumerate(cached_results) if v is None]
            miss_texts = [texts[i] for i in miss_indices]
        else:
            miss_indices = list(range(len(texts)))
            miss_texts = texts

        client = await self._get_client()

        payload: dict[str, object] = {
            "model": self._model,
            "input": miss_texts,
            "dimensions": self._dimensions,
            "task": self.TASK_PASSAGE,
        }

        try:
            response = await self._request_with_backoff(client, payload)
        except httpx.HTTPStatusError as e:
            logger.error(
                "jina_api_error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise JinaEmbeddingError(f"Jina API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("jina_request_error", error=str(e))
            raise JinaEmbeddingError(f"Failed to connect to Jina API: {e}") from e

        data = response.json()
        items = data.get("data")
        if not items or not isinstance(items, list):
            raise JinaEmbeddingError(f"Unexpected response: missing 'data' in {list(data.keys())}")

        fetched: list[list[float]] = [item["embedding"] for item in items]

        if self._embedding_cache:
            for text, vector in zip(miss_texts, fetched, strict=True):
                await self._embedding_cache.set(text, self.TASK_PASSAGE, vector)
            embeddings: list[list[float]] = list(cached_results)  # type: ignore[arg-type]
            for idx, vector in zip(miss_indices, fetched, strict=True):
                embeddings[idx] = vector
        else:
            embeddings = fetched

        logger.debug("jina_embed_complete", count=len(embeddings))
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.

        Raises:
            JinaEmbeddingError: If the API request fails.
        """
        embeddings = await self.embed([text])
        return embeddings[0]

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query.

        Uses retrieval.query task type for better search performance.

        Args:
            query: Search query text.

        Returns:
            Query embedding vector.

        Raises:
            JinaEmbeddingError: If the API request fails.
        """
        if self._embedding_cache:
            cached = await self._embedding_cache.get(query, self.TASK_QUERY)
            if cached is not None:
                return cached

        client = await self._get_client()

        payload: dict[str, object] = {
            "model": self._model,
            "input": [query],
            "dimensions": self._dimensions,
            "task": self.TASK_QUERY,
        }

        try:
            response = await self._request_with_backoff(client, payload)
        except httpx.HTTPStatusError as e:
            logger.error(
                "jina_api_error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise JinaEmbeddingError(f"Jina API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("jina_request_error", error=str(e))
            raise JinaEmbeddingError(f"Failed to connect to Jina API: {e}") from e

        data = response.json()
        items = data.get("data")
        if not items or not isinstance(items, list):
            raise JinaEmbeddingError(f"Unexpected response: missing 'data' in {list(data.keys())}")

        embedding: list[float] = items[0]["embedding"]
        if self._embedding_cache:
            await self._embedding_cache.set(query, self.TASK_QUERY, embedding)
        logger.debug("jina_embed_query_complete")
        return embedding

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
