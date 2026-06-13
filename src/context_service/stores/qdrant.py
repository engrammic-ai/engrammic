"""Qdrant vector database client for semantic search."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import trace
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import ScalarQuantization, ScalarQuantizationConfig, ScalarType

from context_service.config.logging import get_logger
from context_service.engine.storage_circuit import STORE_QDRANT, guard_hard_fail
from context_service.telemetry.metrics import record_db_query

tracer = trace.get_tracer(__name__)

if TYPE_CHECKING:
    from context_service.config.settings import Settings

logger = get_logger(__name__)


COLLECTION_PREFIX = "ctx_"
DENSE_VECTOR_NAME = "dense"


def get_collection_name(silo_id: str) -> str:
    """Return per-silo collection name."""
    return f"{COLLECTION_PREFIX}{silo_id}"


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
        vector_size: int,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        collection_name: str = "context_vectors",
        scalar_quantization: bool = False,
        always_ram: bool = True,
    ) -> None:
        """Initialize the Qdrant client.

        Args:
            vector_size: Dimension of embedding vectors. Must be provided
                explicitly; use ``from_settings`` to derive from config.
            url: Qdrant server URL.
            api_key: Optional API key for authentication.
            collection_name: Qdrant collection name.
            scalar_quantization: When True, enables INT8 scalar quantization on
                new collections to reduce search latency.
            always_ram: When True, keeps quantized vectors in RAM for fastest
                access. Only relevant when scalar_quantization is True.
        """
        self._url = url
        self._api_key = api_key
        self._vector_size = vector_size
        self._collection_name = collection_name
        self._scalar_quantization = scalar_quantization
        self._always_ram = always_ram
        self._client: AsyncQdrantClient | None = None
        self._init_lock: asyncio.Lock = asyncio.Lock()
        self._hybrid_mode: bool = False
        self._collection_ensured: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantClient:
        """Create a QdrantClient from application settings.

        Args:
            settings: Application settings instance.

        Returns:
            Configured QdrantClient.
        """
        models = settings.models
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        return cls(
            url=settings.qdrant_url,
            api_key=api_key,
            vector_size=models.embedding_dimensions,
            collection_name=models.qdrant_collection,
            scalar_quantization=settings.qdrant_scalar_quantization_enabled,
            always_ram=settings.qdrant_quantization_always_ram,
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

    def get_quantization_config(self) -> ScalarQuantization | None:
        """Return the quantization config for collection creation, or None if disabled."""
        if not self._scalar_quantization:
            return None
        return ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                always_ram=self._always_ram,
            )
        )

    async def ensure_collection(self, *, hybrid: bool = False) -> None:
        """Create the collection if it doesn't exist.

        Args:
            hybrid: When True, declares both dense and sparse named-vector
                configs (Qdrant 1.10+). Existing collections are left as-is
                with a warning if the mode differs.
        """
        self._hybrid_mode = hybrid
        client = await self._get_client()
        start = time.perf_counter()
        try:
            collections = await client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self._collection_name not in collection_names:
                quant_config = (
                    ScalarQuantization(
                        scalar=ScalarQuantizationConfig(
                            type=ScalarType.INT8,
                            always_ram=self._always_ram,
                        )
                    )
                    if self._scalar_quantization
                    else None
                )
                if hybrid:
                    await client.create_collection(
                        collection_name=self._collection_name,
                        vectors_config={
                            DENSE_VECTOR_NAME: models.VectorParams(
                                size=self._vector_size,
                                distance=models.Distance.COSINE,
                            ),
                        },
                        sparse_vectors_config={
                            SPARSE_VECTOR_NAME: models.SparseVectorParams(),
                        },
                        quantization_config=quant_config,
                    )
                else:
                    await client.create_collection(
                        collection_name=self._collection_name,
                        vectors_config=models.VectorParams(
                            size=self._vector_size,
                            distance=models.Distance.COSINE,
                        ),
                        quantization_config=quant_config,
                    )
                logger.info(
                    "qdrant_collection_created",
                    collection=self._collection_name,
                    hybrid=hybrid,
                )
            else:
                if hybrid:
                    logger.warning(
                        "qdrant_collection_exists_hybrid_mismatch",
                        collection=self._collection_name,
                        message=(
                            "Collection exists; if created without hybrid mode, "
                            "named-vector upserts will fail. Recreate to enable hybrid."
                        ),
                    )
                else:
                    logger.debug("qdrant_collection_exists", collection=self._collection_name)
                await self._check_dimension_mismatch(client)
            self._collection_ensured = True
        except Exception as e:
            self._client = None
            logger.error("qdrant_ensure_collection_failed", error=str(e))
            raise QdrantOperationError(f"Failed to ensure collection: {e}") from e
        finally:
            record_db_query("qdrant.ensure_collection", (time.perf_counter() - start) * 1000)

    async def _check_dimension_mismatch(self, client: AsyncQdrantClient) -> None:
        """Warn if the configured vector size differs from the existing collection's size.

        For hybrid collections, ``vectors`` is a dict of named VectorParams; for
        non-hybrid collections it is a single VectorParams object.  Both cases
        are handled.  Any failure to retrieve or parse collection info is logged
        and silently ignored so that normal startup is never blocked.
        """
        try:
            collection_info = await client.get_collection(self._collection_name)
            vectors_config = collection_info.config.params.vectors

            if isinstance(vectors_config, dict):
                # Hybrid collection — check the dense vector config.
                dense = vectors_config.get(DENSE_VECTOR_NAME)
                existing_size: int | None = dense.size if dense is not None else None
            else:
                existing_size = vectors_config.size if vectors_config is not None else None

            if existing_size is not None and existing_size != self._vector_size:
                logger.warning(
                    "qdrant_dimension_mismatch",
                    configured=self._vector_size,
                    existing=existing_size,
                    hint=(
                        "Re-embed all documents before switching Matryoshka dimensions. "
                        "See context/specs/2026-05-19-recall-optimization.md Task 4."
                    ),
                )
        except Exception as exc:
            logger.debug(
                "qdrant_dimension_check_skipped",
                error=str(exc),
            )

    async def ensure_reasoning_chains_collection(self) -> None:
        """Ensure the reasoning_chains collection exists for TX6 CONSENSUS.

        This collection stores conclusion embeddings for reasoning chains,
        enabling consensus detection via ANN similarity search.
        """
        collection_name = "reasoning_chains"
        start = time.perf_counter()
        try:
            client = await self._get_client()
            collections = await client.get_collections()
            exists = any(c.name == collection_name for c in collections.collections)
            if not exists:
                quant_config = self.get_quantization_config()
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=self._vector_size,
                        distance=models.Distance.COSINE,
                    ),
                    quantization_config=quant_config,
                )
                logger.info("qdrant_reasoning_chains_collection_created")
            else:
                logger.debug("qdrant_reasoning_chains_collection_exists")
        except Exception as e:
            logger.error("qdrant_ensure_reasoning_chains_failed", error=str(e))
            raise QdrantOperationError(f"Failed to ensure reasoning_chains collection: {e}") from e
        finally:
            record_db_query("qdrant.ensure_reasoning_chains", (time.perf_counter() - start) * 1000)

    async def health_check(self) -> bool:
        """Check if Qdrant is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        start = time.perf_counter()
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception as e:
            logger.warning("qdrant_health_check_failed", error=str(e))
            return False
        finally:
            record_db_query("qdrant.health_check", (time.perf_counter() - start) * 1000)

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

        Raises:
            StorageCircuitOpenError: If the Qdrant circuit breaker is open.
            QdrantOperationError: If the upsert fails.
        """
        return await guard_hard_fail(
            STORE_QDRANT,
            self._upsert_impl(
                node_id, vector, payload, silo_id, sparse_indices, sparse_values, expansion
            ),
        )

    async def _upsert_impl(
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
        start = time.perf_counter()
        with tracer.start_as_current_span(
            "qdrant.upsert", attributes={"node_id": node_id, "hybrid": has_sparse}
        ):
            try:
                # Hybrid collections require named vectors even without sparse
                if self._hybrid_mode:
                    point_vector: Any = {DENSE_VECTOR_NAME: vector}
                    if has_sparse:
                        assert sparse_indices is not None and sparse_values is not None
                        point_vector[SPARSE_VECTOR_NAME] = models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        )
                else:
                    point_vector = vector

                await client.upsert(
                    collection_name=self._collection_name,
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
            finally:
                record_db_query("qdrant.upsert", (time.perf_counter() - start) * 1000)

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

        Raises:
            StorageCircuitOpenError: If the Qdrant circuit breaker is open.
            QdrantOperationError: If the search fails.
        """
        return await guard_hard_fail(
            STORE_QDRANT,
            self._search_impl(
                vector,
                limit,
                score_threshold,
                silo_id,
                filter_conditions,
                search_mode,
                sparse_indices,
                sparse_values,
            ),
        )

    async def _search_impl(
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

        must_conditions: list[
            models.FieldCondition
            | models.IsEmptyCondition
            | models.IsNullCondition
            | models.HasIdCondition
            | models.HasVectorCondition
            | models.NestedCondition
            | models.Filter
        ] = []
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
            models.Filter(must=must_conditions) if must_conditions else None
        )

        has_sparse = sparse_indices is not None and sparse_values is not None

        effective_mode = search_mode
        if search_mode == "hybrid" and not has_sparse:
            logger.warning(
                "qdrant_hybrid_fallback",
                reason="sparse_indices/values not provided; falling back to dense",
            )
            effective_mode = "dense"

        start = time.perf_counter()
        with tracer.start_as_current_span(
            "qdrant.search", attributes={"limit": limit, "mode": effective_mode}
        ):
            try:
                if effective_mode == "sparse":
                    if not has_sparse:
                        raise QdrantOperationError(
                            "sparse_indices and sparse_values are required for sparse mode"
                        )
                    assert sparse_indices is not None and sparse_values is not None
                    response = await client.query_points(
                        collection_name=self._collection_name,
                        query=models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                        using=SPARSE_VECTOR_NAME,
                        limit=limit,
                        score_threshold=score_threshold,
                        query_filter=query_filter,
                    )
                elif effective_mode == "hybrid":
                    # hybrid mode guaranteed to have sparse by earlier check
                    assert sparse_indices is not None and sparse_values is not None
                    response = await client.query_points(
                        collection_name=self._collection_name,
                        prefetch=[
                            models.Prefetch(
                                query=vector,
                                using=DENSE_VECTOR_NAME,
                                filter=query_filter,
                                limit=limit * 2,
                            ),
                            models.Prefetch(
                                query=models.SparseVector(
                                    indices=sparse_indices,
                                    values=sparse_values,
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
                    # Hybrid collections require named vector reference
                    using = DENSE_VECTOR_NAME if self._hybrid_mode else None
                    response = await client.query_points(
                        collection_name=self._collection_name,
                        query=vector,
                        using=using,
                        limit=limit,
                        score_threshold=score_threshold,
                        query_filter=query_filter,
                    )

                results = [
                    SearchResult(
                        node_id=str(r.id),
                        score=r.score if r.score is not None else 0.0,
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
                if e.status_code == 404:
                    logger.warning(
                        "qdrant_collection_not_found_recreating",
                        collection=self._collection_name,
                        hybrid=self._hybrid_mode,
                    )
                    await self.ensure_collection(hybrid=self._hybrid_mode)
                    return []
                logger.error("qdrant_search_error", error=str(e))
                raise QdrantOperationError(f"Failed to search vectors: {e}") from e
            except Exception as e:
                logger.error("qdrant_search_unexpected_error", error=str(e))
                raise QdrantOperationError(f"Failed to search vectors: {e}") from e
            finally:
                record_db_query("qdrant.search", (time.perf_counter() - start) * 1000)

    async def delete(self, node_id: str) -> bool:
        """Delete a vector by node ID.

        Raises:
            StorageCircuitOpenError: If the Qdrant circuit breaker is open.
            QdrantOperationError: If the delete fails.
        """
        return await guard_hard_fail(STORE_QDRANT, self._delete_impl(node_id))

    async def _delete_impl(self, node_id: str) -> bool:
        """Delete a vector by node ID.

        Args:
            node_id: Context node ID.

        Returns:
            True if deleted (or didn't exist).

        Raises:
            QdrantOperationError: If the delete fails.
        """
        client = await self._get_client()
        start = time.perf_counter()
        try:
            await client.delete(
                collection_name=self._collection_name,
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
        finally:
            record_db_query("qdrant.delete", (time.perf_counter() - start) * 1000)

    async def delete_silo_collection(self, silo_id: str) -> bool:
        """Delete entire collection for a silo (GDPR erasure)."""
        collection = get_collection_name(silo_id)
        client = await self._get_client()
        start = time.perf_counter()
        try:
            await client.delete_collection(collection)
            logger.info("qdrant_silo_collection_deleted", silo_id=silo_id, collection=collection)
            return True
        except UnexpectedResponse as e:
            if "not found" in str(e).lower():
                logger.debug("qdrant_silo_collection_not_found", silo_id=silo_id)
                return False
            raise QdrantOperationError(f"Failed to delete silo collection: {e}") from e
        finally:
            record_db_query("qdrant.delete_collection", (time.perf_counter() - start) * 1000)

    async def close(self) -> None:
        """Close the Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.debug("qdrant_client_closed")
