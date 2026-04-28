"""Per-tenant Qdrant vector operations for the engine layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qdrant_client.models import (
    Distance,
    FieldCondition,
    MatchValue,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from qdrant_client.models import Filter as QdrantFilter

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    import uuid

    from context_service.stores.qdrant import QdrantClient

logger = get_logger(__name__)


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

    def _collection_name(self, silo_id: str) -> str:
        return f"{self.COLLECTION_PREFIX}{silo_id}"

    async def _ensure_collection(self, silo_id: str) -> str:
        name = self._collection_name(silo_id)
        if name not in self._ensured_collections:
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
                    )
                else:
                    await client.create_collection(
                        collection_name=name,
                        vectors_config=VectorParams(
                            size=self._qdrant._vector_size,
                            distance=Distance.COSINE,
                        ),
                    )
                logger.info(f"Created Qdrant collection: {name} (hybrid={self._hybrid})")
            self._ensured_collections.add(name)
        return name

    async def upsert(
        self,
        node_id: uuid.UUID,
        vector: list[float],
        silo_id: str,
        node_type: str | None = None,
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
    ) -> None:
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()
        payload: dict[str, Any] = {"silo_id": silo_id}
        if node_type:
            payload["type"] = node_type

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

        await client.upsert(
            collection_name=collection,
            points=[point],
        )

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

            payload: dict[str, Any] = {"silo_id": str(item_silo_id)}
            if node_type:
                payload["type"] = node_type

            if self._hybrid:
                vectors: dict[str, Any] = {self.DENSE_VECTOR_NAME: vector}
                if sparse_indices is not None and sparse_values is not None:
                    vectors[self.SPARSE_VECTOR_NAME] = SparseVector(
                        indices=sparse_indices, values=sparse_values
                    )
                points.append(PointStruct(id=str(node_id), vector=vectors, payload=payload))
            else:
                points.append(PointStruct(id=str(node_id), vector=vector, payload=payload))

        await client.upsert(collection_name=collection, points=points)

    async def delete(self, node_id: uuid.UUID, silo_id: str) -> None:
        collection = await self._ensure_collection(silo_id)
        client = await self._qdrant._get_client()
        from qdrant_client.models import PointIdsList

        await client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=[str(node_id)]),
        )

    async def delete_collection(self, silo_id: str) -> None:
        """Delete entire tenant collection (for GDPR erasure)."""
        name = self._collection_name(silo_id)
        client = await self._qdrant._get_client()
        await client.delete_collection(name)
        self._ensured_collections.discard(name)
        logger.info(f"Deleted Qdrant collection: {name}")

    # --- Cluster summary collection methods ---

    CLUSTER_COLLECTION_PREFIX = "ctx_clusters_"

    def _cluster_collection_name(self, silo_id: str) -> str:
        return f"{self.CLUSTER_COLLECTION_PREFIX}{silo_id}"

    async def ensure_cluster_collection(self, silo_id: str) -> str:
        """Create cluster summary collection if it does not exist."""
        name = self._cluster_collection_name(silo_id)
        if name not in self._ensured_collections:
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
                )
                logger.info(f"Created cluster Qdrant collection: {name}")
            self._ensured_collections.add(name)
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
        await client.upsert(collection_name=collection, points=[point])

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
        await client.upsert(collection_name=collection, points=points)
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

        response = await client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
        )
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
        try:
            await client.delete_collection(name)
            self._ensured_collections.discard(name)
            logger.info(f"Deleted cluster Qdrant collection: {name}")
        except Exception:
            logger.debug(f"Cluster collection {name} not found, skipping delete")
