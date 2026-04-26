"""Qdrant vector database client for semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.config.settings import Settings

logger = get_logger(__name__)

COLLECTION_NAME = "context_vectors"


class QdrantOperationError(Exception):
    """Raised when a Qdrant operation fails."""


@dataclass
class SearchResult:
    """Represents a vector search result."""

    node_id: str
    score: float
    payload: dict[str, Any]


class QdrantClient:
    """High-level Qdrant client for vector operations."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        vector_size: int = 1024,
    ) -> None:
        """Initialize the Qdrant client.

        Args:
            url: Qdrant server URL.
            api_key: Optional API key for authentication.
            vector_size: Dimension of embedding vectors.
        """
        self._url = url
        self._api_key = api_key
        self._vector_size = vector_size
        self._client: AsyncQdrantClient | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantClient:
        """Create a QdrantClient from application settings.

        Args:
            settings: Application settings instance.

        Returns:
            Configured QdrantClient.
        """
        api_key = settings.qdrant_api_key or None
        return cls(
            url=settings.qdrant_url,
            api_key=api_key if api_key else None,
            vector_size=1024,  # Default Jina dimensions
        )

    async def _get_client(self) -> AsyncQdrantClient:
        """Get or create the Qdrant client."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=self._url,
                api_key=self._api_key,
            )
        return self._client

    async def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        client = await self._get_client()

        try:
            collections = await client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if COLLECTION_NAME not in collection_names:
                await client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=self._vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("qdrant_collection_created", collection=COLLECTION_NAME)
            else:
                logger.debug("qdrant_collection_exists", collection=COLLECTION_NAME)
        except Exception as e:
            self._client = None
            logger.error("qdrant_ensure_collection_failed", error=str(e))
            raise QdrantOperationError(f"Failed to ensure collection: {e}") from e

    async def health_check(self) -> bool:
        """Check if Qdrant is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception as e:
            logger.warning("qdrant_health_check_failed", error=str(e))
            return False

    async def upsert(
        self,
        node_id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
        silo_id: str | None = None,
    ) -> bool:
        """Insert or update a vector.

        Args:
            node_id: Unique identifier for the vector.
            vector: Embedding vector.
            payload: Optional metadata to store with the vector.
            silo_id: Optional silo identifier for payload filtering.

        Returns:
            True if successful.

        Raises:
            QdrantOperationError: If the upsert fails.
        """
        client = await self._get_client()

        point_payload = payload or {}
        point_payload["node_id"] = node_id
        if silo_id is not None:
            point_payload["silo_id"] = silo_id

        try:
            await client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=node_id,
                        vector=vector,
                        payload=point_payload,
                    )
                ],
            )
            logger.debug("qdrant_upsert", node_id=node_id)
            return True
        except UnexpectedResponse as e:
            logger.error("qdrant_upsert_error", node_id=node_id, error=str(e))
            raise QdrantOperationError(f"Failed to upsert vector: {e}") from e
        except Exception as e:
            logger.error("qdrant_upsert_unexpected_error", node_id=node_id, error=str(e))
            raise QdrantOperationError(f"Failed to upsert vector: {e}") from e

    async def search(
        self,
        vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
        silo_id: str | None = None,
        filter_conditions: list[models.FieldCondition] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors.

        Args:
            vector: Query embedding vector.
            limit: Maximum number of results.
            score_threshold: Minimum similarity score (0-1 for cosine).
            silo_id: Optional silo identifier to scope results.
            filter_conditions: Additional filter conditions.

        Returns:
            List of search results ordered by similarity.

        Raises:
            QdrantOperationError: If the search fails.
        """
        client = await self._get_client()

        must_conditions: list[models.FieldCondition] = []
        if silo_id is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="silo_id",
                    match=models.MatchValue(value=silo_id),
                )
            )
        if filter_conditions:
            must_conditions.extend(filter_conditions)
        query_filter = models.Filter(must=must_conditions) if must_conditions else None

        try:
            response = await client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )

            results = [
                SearchResult(
                    node_id=str(r.id),
                    score=r.score,
                    payload=r.payload or {},
                )
                for r in response.points
            ]

            logger.debug("qdrant_search", result_count=len(results))
            return results
        except UnexpectedResponse as e:
            logger.error("qdrant_search_error", error=str(e))
            raise QdrantOperationError(f"Failed to search vectors: {e}") from e
        except Exception as e:
            logger.error("qdrant_search_unexpected_error", error=str(e))
            raise QdrantOperationError(f"Failed to search vectors: {e}") from e

    async def delete(self, node_id: str) -> bool:
        """Delete a vector by node ID.

        Args:
            node_id: Context node ID.

        Returns:
            True if deleted (or didn't exist).

        Raises:
            QdrantOperationError: If the delete fails.
        """
        client = await self._get_client()

        try:
            await client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.PointIdsList(
                    points=[node_id],
                ),
            )
            logger.debug("qdrant_delete", node_id=node_id)
            return True
        except UnexpectedResponse as e:
            logger.error("qdrant_delete_error", node_id=node_id, error=str(e))
            raise QdrantOperationError(f"Failed to delete vector: {e}") from e
        except Exception as e:
            logger.error("qdrant_delete_unexpected_error", node_id=node_id, error=str(e))
            raise QdrantOperationError(f"Failed to delete vector: {e}") from e

    async def close(self) -> None:
        """Close the Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.debug("qdrant_client_closed")
