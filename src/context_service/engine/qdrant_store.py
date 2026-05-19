"""Per-tenant Qdrant vector operations for the engine layer."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Fusion,
    FusionQuery,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from qdrant_client.models import Filter as QdrantFilter

from context_service.config.logging import get_logger
from context_service.stores.qdrant import QdrantOperationError
from context_service.telemetry.metrics import record_db_query

if TYPE_CHECKING:
    import uuid

    from context_service.stores.qdrant import QdrantClient

logger = get_logger(__name__)

SearchMode = Literal["hybrid", "dense", "sparse"]


@dataclass
class ClusterSearchResult:
    """Result from cluster summary vector search."""

    cluster_id: str
    score: float
    level: int
    node_count: int


@dataclass
class VectorSearchResult:
    """Result from vector search."""

    node_id: str
    score: float
    silo_id: str | None
    node_type: str | None
    vector: list[float] | None = None  # Populated only when with_vectors=True on search


class EngineQdrantStore:
    """Per-tenant Qdrant collection management with optional hybrid search."""

    COLLECTION_PREFIX = "ctx_"
    DENSE_VECTOR_NAME = "dense"
    SPARSE_VECTOR_NAME = "sparse"

    def __init__(self, qdrant_client: QdrantClient, *, hybrid: bool = False) -> None:
        self._qdrant = qdrant_client
        self._ensured_collections: set[str] = set()
        self._hybrid = hybrid
        self._ensure_lock: asyncio.Lock = asyncio.Lock()

    async def close(self) -> None:
        """Release the underlying Qdrant client connection."""
        await self._qdrant.close()

    def _collection_name(self, silo_id: str) -> str:
        return f"{self.COLLECTION_PREFIX}{silo_id}"

    async def _ensure_collection(self, silo_id: str) -> str:
        name = self._collection_name(silo_id)
        if name in self._ensured_collections:
            return name
        async with self._ensure_lock:
            # Double-checked locking: another coroutine may have created it while we waited.
            if name in self._ensured_collections:
                return name
            start = time.perf_counter()
            try:
                client = await self._qdrant._get_client()
                collections = await client.get_collections()
                existing = {c.name for c in collections.collections}
                if name in existing and self._hybrid:
                    logger.warning(
                        f"Collection {name} exists; if created without hybrid mode, "
                        f"named-vector upserts will fail. Recreate to enable hybrid."
                    )
                if name not in existing:
                    if self._hybrid:
                        await client.create_collection(
                            collection_name=name,
                            vectors_config={
                                self.DENSE_VECTOR_NAME: VectorParams(
                                    size=self._qdrant._vector_size,
                                    distance=Distance.COSINE,
                                ),
                            },
                            sparse_vectors_config={
                                self.SPARSE_VECTOR_NAME: SparseVectorParams(),
                            },
                            quantization_config=self._qdrant.get_quantization_config(),
                        )
                    else:
                        await client.create_collection(
                            collection_name=name,
                            vectors_config=VectorParams(
                                size=self._qdrant._vector_size,
                                distance=Distance.COSINE,
                            ),
                            quantization_config=self._qdrant.get_quantization_config(),
                        )
                    try:
                        await client.create_payload_index(
                            collection_name=name,
                            field_name="expansion",
                            field_schema=PayloadSchemaType.TEXT,
                        )
                    except (UnexpectedResponse, ConnectionError) as e:
                        logger.error(
                            "Failed to create payload index; deleting collection to avoid partial state",
                            collection=name,
                            error=str(e),
                        )
                        with contextlib.suppress(Exception):
                            await client.delete_collection(name)
                        raise QdrantOperationError(
                            f"Failed to create payload index for collection {name}: {e}"
                        ) from e
                    logger.info(f"Created Qdrant collection: {name} (hybrid={self._hybrid})")
                self._ensured_collections.add(name)
            except QdrantOperationError:
                raise
            except Exception as e:
                logger.error("Failed to ensure Qdrant collection", collection=name, error=str(e))
                raise QdrantOperationError(f"Failed to ensure collection {name}: {e}") from e
            finally:
                record_db_query(
                    "qdrant_store.ensure_collection", (time.perf_counter() - start) * 1000
                )
        return name

    async def upsert(
        self,
        node_id: uuid.UUID,
        vector: list[float],
        silo_id: str,
        node_type: str | None = None,
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
        expansion: str | None = None,
    ) -> None:
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()
        payload: dict[str, Any] = {"silo_id": silo_id}
        if node_type:
            payload["type"] = node_type
        if expansion is not None:
            payload["expansion"] = expansion

        if self._hybrid:
            vectors: dict[str, Any] = {
                self.DENSE_VECTOR_NAME: vector,
            }
            if sparse_indices is not None and sparse_values is not None:
                vectors[self.SPARSE_VECTOR_NAME] = SparseVector(
                    indices=sparse_indices, values=sparse_values
                )
            point = PointStruct(
                id=str(node_id),
                vector=vectors,
                payload=payload,
            )
        else:
            point = PointStruct(
                id=str(node_id),
                vector=vector,
                payload=payload,
            )

        start = time.perf_counter()
        try:
            await client.upsert(
                collection_name=collection,
                points=[point],
            )
        except (UnexpectedResponse, ConnectionError) as e:
            logger.error("Qdrant upsert failed", node_id=str(node_id), error=str(e))
            raise
        finally:
            record_db_query("qdrant_store.upsert", (time.perf_counter() - start) * 1000)

    async def batch_upsert(
        self,
        items: list[dict[str, Any]],
        silo_id: str,
    ) -> None:
        """Upsert many points in a single Qdrant call.

        Each ``items`` element is a dict with keys:
        - ``node_id`` (uuid.UUID | str, required)
        - ``vector`` (list[float], required)
        - ``silo_id`` (uuid.UUID | str | None, optional)
        - ``node_type`` (str | None, optional)
        - ``sparse_indices`` (list[int] | None, optional)
        - ``sparse_values`` (list[float] | None, optional)
        - ``expansion`` (str | None, optional)

        Writes one PointStruct per item and sends a single ``client.upsert``
        request. Honors ``self._hybrid`` the same way ``upsert`` does.
        """
        if not items:
            return
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()

        points: list[PointStruct] = []
        for item in items:
            node_id = item["node_id"]
            vector = item["vector"]
            item_silo_id = item.get("silo_id") or silo_id
            node_type = item.get("node_type")
            sparse_indices = item.get("sparse_indices")
            sparse_values = item.get("sparse_values")
            expansion = item.get("expansion")

            payload: dict[str, Any] = {"silo_id": str(item_silo_id)}
            if node_type:
                payload["type"] = node_type
            if expansion is not None:
                payload["expansion"] = expansion

            if self._hybrid:
                vectors: dict[str, Any] = {self.DENSE_VECTOR_NAME: vector}
                if sparse_indices is not None and sparse_values is not None:
                    vectors[self.SPARSE_VECTOR_NAME] = SparseVector(
                        indices=sparse_indices, values=sparse_values
                    )
                points.append(PointStruct(id=str(node_id), vector=vectors, payload=payload))
            else:
                points.append(PointStruct(id=str(node_id), vector=vector, payload=payload))

        start = time.perf_counter()
        try:
            await client.upsert(collection_name=collection, points=points)
        except Exception as e:
            logger.error(
                "Qdrant batch_upsert failed", silo_id=silo_id, count=len(points), error=str(e)
            )
            raise QdrantOperationError(f"Failed to batch upsert vectors: {e}") from e
        finally:
            record_db_query("qdrant_store.batch_upsert", (time.perf_counter() - start) * 1000)

    async def query(
        self,
        vector: list[float],
        silo_id: str,
        *,
        limit: int = 10,
        search_mode: SearchMode = "hybrid",
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using the specified retrieval mode.

        For ``search_mode="hybrid"`` the method issues a Qdrant Query API
        request with two prefetch legs (dense + sparse) fused via RRF.
        Dense-only and sparse-only modes issue a single-leg query.

        In hybrid mode, ``sparse_indices`` and ``sparse_values`` are required;
        if they are not supplied, the method falls back to dense-only mode
        with a warning.

        Args:
            vector: Dense query vector.
            silo_id: Tenant silo identifier (used for collection scoping and
                payload filter).
            limit: Maximum number of results.
            search_mode: ``"hybrid"``, ``"dense"``, or ``"sparse"``.
            sparse_indices: Sparse vector token indices (required for hybrid /
                sparse modes).
            sparse_values: Sparse vector activation values (required for hybrid
                / sparse modes).
            score_threshold: Optional minimum score filter.

        Returns:
            List of :class:`VectorSearchResult` ordered by descending score.
        """
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()

        must: list[Any] = [FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
        query_filter = QdrantFilter(must=must)

        has_sparse = sparse_indices is not None and sparse_values is not None

        effective_mode = search_mode
        if search_mode == "hybrid" and not has_sparse:
            logger.warning(
                "splade_hybrid_fallback",
                reason="sparse_indices/values not provided; falling back to dense",
            )
            effective_mode = "dense"

        start = time.perf_counter()
        try:
            if effective_mode == "dense":
                response = await client.query_points(
                    collection_name=collection,
                    query=vector,
                    using=self.DENSE_VECTOR_NAME if self._hybrid else None,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
            elif effective_mode == "sparse":
                if not has_sparse:
                    raise ValueError(
                        "sparse_indices and sparse_values are required for sparse mode"
                    )
                response = await client.query_points(
                    collection_name=collection,
                    query=SparseVector(
                        indices=sparse_indices,  # type: ignore[arg-type]
                        values=sparse_values,  # type: ignore[arg-type]
                    ),
                    using=self.SPARSE_VECTOR_NAME,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
            else:
                # Hybrid: RRF fusion over dense + sparse prefetch legs.
                response = await client.query_points(
                    collection_name=collection,
                    prefetch=[
                        Prefetch(
                            query=vector,
                            using=self.DENSE_VECTOR_NAME,
                            filter=query_filter,
                            limit=limit * 2,
                        ),
                        Prefetch(
                            query=SparseVector(
                                indices=sparse_indices,  # type: ignore[arg-type]
                                values=sparse_values,  # type: ignore[arg-type]
                            ),
                            using=self.SPARSE_VECTOR_NAME,
                            filter=query_filter,
                            limit=limit * 2,
                        ),
                    ],
                    query=FusionQuery(fusion=Fusion.RRF),
                    limit=limit,
                    score_threshold=score_threshold,
                )
        except QdrantOperationError:
            raise
        except Exception as e:
            logger.error("Qdrant query failed", silo_id=silo_id, mode=effective_mode, error=str(e))
            raise QdrantOperationError(f"Failed to query vectors: {e}") from e
        finally:
            record_db_query("qdrant_store.query", (time.perf_counter() - start) * 1000)

        return [
            VectorSearchResult(
                node_id=str(r.id),
                score=r.score,
                silo_id=r.payload.get("silo_id") if r.payload else None,
                node_type=r.payload.get("type") if r.payload else None,
            )
            for r in response.points
        ]

    async def delete(self, node_id: uuid.UUID, silo_id: str) -> None:
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()
        from qdrant_client.models import PointIdsList

        start = time.perf_counter()
        try:
            await client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=[str(node_id)]),
            )
        except Exception as e:
            logger.error(
                "Qdrant delete failed", node_id=str(node_id), silo_id=silo_id, error=str(e)
            )
            raise QdrantOperationError(f"Failed to delete vector {node_id}: {e}") from e
        finally:
            record_db_query("qdrant_store.delete", (time.perf_counter() - start) * 1000)

    async def delete_collection(self, silo_id: str) -> None:
        """Delete entire tenant collection (for GDPR erasure)."""
        name = self._collection_name(silo_id)
        client = await self._qdrant._get_client()
        start = time.perf_counter()
        try:
            await client.delete_collection(name)
        except Exception as e:
            logger.error("Qdrant delete_collection failed", collection=name, error=str(e))
            raise QdrantOperationError(f"Failed to delete collection {name}: {e}") from e
        finally:
            record_db_query("qdrant_store.delete_collection", (time.perf_counter() - start) * 1000)
        self._ensured_collections.discard(name)
        logger.info(f"Deleted Qdrant collection: {name}")

    # --- Cluster summary collection methods ---

    CLUSTER_COLLECTION_PREFIX = "ctx_clusters_"

    def _cluster_collection_name(self, silo_id: str) -> str:
        return f"{self.CLUSTER_COLLECTION_PREFIX}{silo_id}"

    async def ensure_cluster_collection(self, silo_id: str) -> str:
        """Create cluster summary collection if it does not exist."""
        name = self._cluster_collection_name(silo_id)
        if name in self._ensured_collections:
            return name
        async with self._ensure_lock:
            if name in self._ensured_collections:
                return name
            start = time.perf_counter()
            try:
                client = await self._qdrant._get_client()
                collections = await client.get_collections()
                existing = {c.name for c in collections.collections}
                if name not in existing:
                    await client.create_collection(
                        collection_name=name,
                        vectors_config=VectorParams(
                            size=self._qdrant._vector_size,
                            distance=Distance.COSINE,
                        ),
                        quantization_config=self._qdrant.get_quantization_config(),
                    )
                    logger.info(f"Created cluster Qdrant collection: {name}")
                self._ensured_collections.add(name)
            except QdrantOperationError:
                raise
            except Exception as e:
                logger.error(
                    "Failed to ensure cluster Qdrant collection", collection=name, error=str(e)
                )
                raise QdrantOperationError(f"Failed to ensure cluster collection: {e}") from e
            finally:
                record_db_query(
                    "qdrant_store.ensure_cluster_collection", (time.perf_counter() - start) * 1000
                )
        return name

    async def upsert_cluster_embedding(
        self,
        cluster_id: str,
        vector: list[float],
        silo_id: str,
        level: int,
        node_count: int,
    ) -> None:
        """Upsert a cluster summary embedding."""
        collection = await self.ensure_cluster_collection(silo_id)
        client = await self._qdrant._get_client()
        point = PointStruct(
            id=cluster_id,
            vector=vector,
            payload={
                "level": level,
                "node_count": node_count,
                "silo_id": silo_id,
            },
        )
        start = time.perf_counter()
        try:
            await client.upsert(collection_name=collection, points=[point])
        except Exception as e:
            logger.error(
                "Qdrant upsert_cluster_embedding failed",
                cluster_id=cluster_id,
                silo_id=silo_id,
                error=str(e),
            )
            raise QdrantOperationError(
                f"Failed to upsert cluster embedding {cluster_id}: {e}"
            ) from e
        finally:
            record_db_query(
                "qdrant_store.upsert_cluster_embedding", (time.perf_counter() - start) * 1000
            )

    async def batch_upsert_cluster_embeddings(
        self,
        items: list[dict[str, Any]],
        silo_id: str,
    ) -> int:
        """Upsert many cluster embeddings in a single Qdrant call. R-007 fix.

        Each item: {cluster_id: str, vector: list[float], level: int, node_count: int}.
        Returns number of points upserted.
        """
        if not items:
            return 0
        collection = await self.ensure_cluster_collection(silo_id)
        client = await self._qdrant._get_client()
        points = [
            PointStruct(
                id=item["cluster_id"],
                vector=item["vector"],
                payload={
                    "level": item.get("level", 0),
                    "node_count": item.get("node_count", 0),
                    "silo_id": silo_id,
                },
            )
            for item in items
        ]
        start = time.perf_counter()
        try:
            await client.upsert(collection_name=collection, points=points)
        except Exception as e:
            logger.error(
                "Qdrant batch_upsert_cluster_embeddings failed",
                silo_id=silo_id,
                count=len(points),
                error=str(e),
            )
            raise QdrantOperationError(f"Failed to batch upsert cluster embeddings: {e}") from e
        finally:
            record_db_query(
                "qdrant_store.batch_upsert_cluster_embeddings", (time.perf_counter() - start) * 1000
            )
        return len(points)

    async def search_clusters(
        self,
        vector: list[float],
        silo_id: str,
        *,
        limit: int = 5,
        level: int | None = None,
    ) -> list[ClusterSearchResult]:
        """Search cluster summaries by vector similarity."""
        collection = await self.ensure_cluster_collection(silo_id)
        client = await self._qdrant._get_client()

        must: list[Any] = []
        if level is not None:
            must.append(FieldCondition(key="level", match=MatchValue(value=level)))
        query_filter = QdrantFilter(must=must) if must else None

        start = time.perf_counter()
        try:
            response = await client.query_points(
                collection_name=collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
            )
        except Exception as e:
            logger.error("Qdrant search_clusters failed", silo_id=silo_id, error=str(e))
            raise QdrantOperationError(f"Failed to search clusters: {e}") from e
        finally:
            record_db_query("qdrant_store.search_clusters", (time.perf_counter() - start) * 1000)
        return [
            ClusterSearchResult(
                cluster_id=str(r.id),
                score=r.score,
                level=r.payload.get("level", 0) if r.payload else 0,
                node_count=r.payload.get("node_count", 0) if r.payload else 0,
            )
            for r in response.points
        ]

    async def delete_cluster_collection(self, silo_id: str) -> None:
        """Delete the cluster summary collection for a tenant."""
        name = self._cluster_collection_name(silo_id)
        client = await self._qdrant._get_client()
        start = time.perf_counter()
        try:
            await client.delete_collection(name)
            self._ensured_collections.discard(name)
            logger.info(f"Deleted cluster Qdrant collection: {name}")
        except Exception:
            logger.debug(f"Cluster collection {name} not found, skipping delete")
        finally:
            record_db_query(
                "qdrant_store.delete_cluster_collection", (time.perf_counter() - start) * 1000
            )
