"""Qdrant vector database client for semantic search."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.config.settings import Settings

logger = get_logger(__name__)


COLLECTION_PREFIX = "ctx_"
DENSE_VECTOR_NAME = "dense"


def get_collection_name(silo_id: str) -> str:
    """Return per-silo collection name."""
    return f"{COLLECTION_PREFIX}{silo_id}"


@lru_cache
def _get_collection_name() -> str:
    """Legacy: load global collection name from config. Deprecated - use get_collection_name(silo_id)."""
    from context_service.config.config_loader import load_config

    logger.warning("_get_collection_name is deprecated, use get_collection_name(silo_id)")
    try:
        config = load_config("embeddings")
        return str(config.get("qdrant_collection", "context_vectors"))
    except FileNotFoundError:
        return "context_vectors"


SPARSE_VECTOR_NAME = "sparse"


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
        self._init_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantClient:
        """Create a QdrantClient from application settings.

        Args:
            settings: Application settings instance.

        Returns:
            Configured QdrantClient.
        """
        from context_service.config.config_loader import load_config

        embed_config = load_config("embeddings")
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        return cls(
            url=settings.qdrant_url,
            api_key=api_key,
            vector_size=embed_config["dimensions"],
        )

    async def _get_client(self) -> AsyncQdrantClient:
        """Get or create the Qdrant client (thread-safe via asyncio lock)."""
        if self._client is None:
            async with self._init_lock:
                if self._client is None:
                    self._client = AsyncQdrantClient(
                        url=self._url,
                        api_key=self._api_key,
                    )
        return self._client

    async def ensure_collection(self, *, hybrid: bool = False) -> None:
        """Create the collection if it doesn't exist.

        Args:
            hybrid: When True, declares both dense and sparse named-vector
                configs (Qdrant 1.10+). Existing collections are left as-is
                with a warning if the mode differs.
        """
        client = await self._get_client()

        try:
            collections = await client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if _get_collection_name() not in collection_names:
                if hybrid:
                    await client.create_collection(
                        collection_name=_get_collection_name(),
                        vectors_config={
                            DENSE_VECTOR_NAME: models.VectorParams(
                                size=self._vector_size,
                                distance=models.Distance.COSINE,
                            ),
                        },
                        sparse_vectors_config={
                            SPARSE_VECTOR_NAME: models.SparseVectorParams(),
                        },
                    )
                else:
                    await client.create_collection(
                        collection_name=_get_collection_name(),
                        vectors_config=models.VectorParams(
                            size=self._vector_size,
                            distance=models.Distance.COSINE,
                        ),
                    )
                logger.info(
                    "qdrant_collection_created",
                    collection=_get_collection_name(),
                    hybrid=hybrid,
                )
            else:
                if hybrid:
                    logger.warning(
                        "qdrant_collection_exists_hybrid_mismatch",
                        collection=_get_collection_name(),
                        message=(
                            "Collection exists; if created without hybrid mode, "
                            "named-vector upserts will fail. Recreate to enable hybrid."
                        ),
                    )
                else:
                    logger.debug("qdrant_collection_exists", collection=_get_collection_name())
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
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
        expansion: str | None = None,
    ) -> bool:
        """Insert or update a vector.

        When ``sparse_indices`` and ``sparse_values`` are provided the point is
        stored with named dense + sparse vectors (hybrid mode). The collection
        must have been created with ``ensure_collection(hybrid=True)``
        beforehand; otherwise Qdrant will reject the named-vector format.

        Args:
            node_id: Unique identifier for the vector.
            vector: Dense embedding vector.
            payload: Optional metadata to store with the vector.
            silo_id: Optional silo identifier for payload filtering.
            sparse_indices: Sparse-vector token indices (SPLADE output).
            sparse_values: Sparse-vector activation values (SPLADE output).
            expansion: Optional predicted-query expansion text stored as a
                payload field for SPLADE encoding at query time.

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
        if expansion is not None:
            point_payload["expansion"] = expansion

        has_sparse = sparse_indices is not None and sparse_values is not None

        try:
            if has_sparse:
                point_vector: Any = {
                    DENSE_VECTOR_NAME: vector,
                    SPARSE_VECTOR_NAME: models.SparseVector(
                        indices=sparse_indices,  # type: ignore[arg-type]
                        values=sparse_values,  # type: ignore[arg-type]
                    ),
                }
            else:
                point_vector = vector

            await client.upsert(
                collection_name=_get_collection_name(),
                points=[
                    models.PointStruct(
                        id=node_id,
                        vector=point_vector,
                        payload=point_payload,
                    )
                ],
            )
            logger.debug("qdrant_upsert", node_id=node_id, hybrid=has_sparse)
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
        search_mode: Literal["hybrid", "dense", "sparse"] = "dense",
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors.

        When ``search_mode="hybrid"``, both dense and sparse prefetch legs are
        issued and fused via RRF. ``sparse_indices`` / ``sparse_values`` are
        required for hybrid and sparse modes; missing them in hybrid mode
        causes an automatic fallback to dense with a warning.

        Args:
            vector: Dense query embedding vector.
            limit: Maximum number of results.
            score_threshold: Minimum similarity score (0-1 for cosine).
            silo_id: Optional silo identifier to scope results.
            filter_conditions: Additional filter conditions.
            search_mode: Retrieval mode — ``"hybrid"``, ``"dense"``, or
                ``"sparse"``.
            sparse_indices: Sparse-vector token indices (required for hybrid /
                sparse modes).
            sparse_values: Sparse-vector activation values (required for hybrid
                / sparse modes).

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
        query_filter: models.Filter | None = (
            models.Filter(must=must_conditions) if must_conditions else None  # type: ignore[arg-type]
        )

        has_sparse = sparse_indices is not None and sparse_values is not None

        effective_mode = search_mode
        if search_mode == "hybrid" and not has_sparse:
            logger.warning(
                "qdrant_hybrid_fallback",
                reason="sparse_indices/values not provided; falling back to dense",
            )
            effective_mode = "dense"

        try:
            if effective_mode == "sparse":
                if not has_sparse:
                    raise QdrantOperationError(
                        "sparse_indices and sparse_values are required for sparse mode"
                    )
                response = await client.query_points(
                    collection_name=_get_collection_name(),
                    query=models.SparseVector(
                        indices=sparse_indices,  # type: ignore[arg-type]
                        values=sparse_values,  # type: ignore[arg-type]
                    ),
                    using=SPARSE_VECTOR_NAME,
                    limit=limit,
                    score_threshold=score_threshold,
                    query_filter=query_filter,
                )
            elif effective_mode == "hybrid":
                response = await client.query_points(
                    collection_name=_get_collection_name(),
                    prefetch=[
                        models.Prefetch(
                            query=vector,
                            using=DENSE_VECTOR_NAME,
                            filter=query_filter,
                            limit=limit * 2,
                        ),
                        models.Prefetch(
                            query=models.SparseVector(
                                indices=sparse_indices,  # type: ignore[arg-type]
                                values=sparse_values,  # type: ignore[arg-type]
                            ),
                            using=SPARSE_VECTOR_NAME,
                            filter=query_filter,
                            limit=limit * 2,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=limit,
                    score_threshold=score_threshold,
                )
            else:
                # Dense-only (default legacy path)
                response = await client.query_points(
                    collection_name=_get_collection_name(),
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

            logger.debug(
                "qdrant_search",
                result_count=len(results),
                search_mode=effective_mode,
            )
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
                collection_name=_get_collection_name(),
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

    async def delete_silo_collection(self, silo_id: str) -> bool:
        """Delete entire collection for a silo (GDPR erasure)."""
        collection = get_collection_name(silo_id)
        client = await self._get_client()
        try:
            await client.delete_collection(collection)
            logger.info("qdrant_silo_collection_deleted", silo_id=silo_id, collection=collection)
            return True
        except UnexpectedResponse as e:
            if "not found" in str(e).lower():
                logger.debug("qdrant_silo_collection_not_found", silo_id=silo_id)
                return False
            raise QdrantOperationError(f"Failed to delete silo collection: {e}") from e

    async def close(self) -> None:
        """Close the Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.debug("qdrant_client_closed")
