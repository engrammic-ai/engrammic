"""Semantic rerank cache - caches rerank scores by query similarity."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from cachetools import TTLCache
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from context_service.telemetry.metrics import (
    record_cache_hit,
    record_cache_miss,
)

if TYPE_CHECKING:
    from context_service.stores.qdrant import QdrantClient

logger = structlog.get_logger(__name__)

RERANK_CACHE_COLLECTION = "rerank_cache"


def _sha256_short(text: str) -> str:
    """Return first 16 chars of SHA256 hash."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _doc_ids_hash(doc_ids: list[str]) -> str:
    """Hash sorted doc IDs for order-independent matching."""
    return _sha256_short(",".join(sorted(doc_ids)))


class SemanticRerankCache:
    """Two-level cache for rerank results.

    L1: Exact match on (query_hash, doc_ids_hash) - TTLCache, in-process
    L2: Semantic match on query embedding with same doc_ids_hash - Qdrant

    Cache hit reuses rerank scores when:
    - L1: Exact same query and document set
    - L2: Similar query (>= threshold) and same document set
    """

    def __init__(
        self,
        qdrant: QdrantClient,
        collection_name: str = RERANK_CACHE_COLLECTION,
        similarity_threshold: float = 0.95,
        l1_ttl_seconds: int = 300,
        l1_maxsize: int = 1000,
    ) -> None:
        self._qdrant = qdrant
        self._collection = collection_name
        self._threshold = similarity_threshold
        self._l1: TTLCache[str, list[tuple[str, float]]] = TTLCache(
            maxsize=l1_maxsize, ttl=l1_ttl_seconds
        )
        self._collection_ensured = False

    async def _get_client(self) -> Any:
        """Get the underlying AsyncQdrantClient."""
        return await self._qdrant._get_client()

    def _l1_key(self, query: str, doc_ids: list[str]) -> str:
        """Build L1 cache key from query and doc IDs."""
        query_hash = _sha256_short(query.lower().strip())
        docs_hash = _doc_ids_hash(doc_ids)
        return f"{query_hash}:{docs_hash}"

    async def _ensure_collection(self) -> None:
        """Create rerank cache collection if it doesn't exist."""
        if self._collection_ensured:
            return

        client = await self._get_client()
        collections = await client.get_collections()
        existing = {c.name for c in collections.collections}

        if self._collection not in existing:
            await client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )
            await client.create_payload_index(
                collection_name=self._collection,
                field_name="silo_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            await client.create_payload_index(
                collection_name=self._collection,
                field_name="doc_ids_hash",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("rerank_cache_collection_created", collection=self._collection)

        self._collection_ensured = True

    async def get(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        silo_id: str,
    ) -> list[tuple[str, float]] | None:
        """Try to get cached rerank scores.

        Args:
            query: The search query
            query_embedding: Pre-computed query embedding (reused from vector search)
            doc_ids: List of document IDs being reranked
            silo_id: Silo ID for scoping

        Returns:
            List of (doc_id, score) tuples if cache hit, None otherwise.
            Scores are in descending order (highest relevance first).
        """
        l1_key = self._l1_key(query, doc_ids)

        # L1: exact match
        if l1_key in self._l1:
            record_cache_hit("rerank_l1", silo_id=silo_id)
            logger.debug("rerank_cache_l1_hit", silo_id=silo_id)
            return self._l1[l1_key]

        # L2: semantic match
        await self._ensure_collection()
        doc_hash = _doc_ids_hash(doc_ids)
        try:
            client = await self._get_client()
            results = await client.search(
                collection_name=self._collection,
                query_vector=query_embedding,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="silo_id", match=MatchValue(value=silo_id)),
                        FieldCondition(key="doc_ids_hash", match=MatchValue(value=doc_hash)),
                    ]
                ),
                limit=1,
                score_threshold=self._threshold,
            )
        except Exception as e:
            logger.warning("rerank_cache_l2_search_failed", error=str(e))
            record_cache_miss("rerank", silo_id=silo_id)
            return None

        if results and results[0].score >= self._threshold:
            scores = results[0].payload.get("scores", [])
            # Convert from stored format back to tuples
            scores_tuples = [(s["doc_id"], s["score"]) for s in scores]
            # Warm L1 for next exact match
            self._l1[l1_key] = scores_tuples
            record_cache_hit("rerank_l2", silo_id=silo_id)
            logger.debug(
                "rerank_cache_l2_hit",
                silo_id=silo_id,
                similarity=round(results[0].score, 3),
            )
            return scores_tuples

        record_cache_miss("rerank", silo_id=silo_id)
        return None

    async def set(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        scores: list[tuple[str, float]],
        silo_id: str,
    ) -> None:
        """Store rerank results in both cache levels.

        Args:
            query: The search query
            query_embedding: Pre-computed query embedding
            doc_ids: List of document IDs that were reranked
            scores: List of (doc_id, score) tuples, highest score first
            silo_id: Silo ID for scoping
        """
        l1_key = self._l1_key(query, doc_ids)
        self._l1[l1_key] = scores

        # L2: store in Qdrant for semantic matching
        await self._ensure_collection()
        point_id = str(uuid.uuid4())
        # Convert tuples to dicts for JSON storage
        scores_payload = [{"doc_id": doc_id, "score": score} for doc_id, score in scores]

        try:
            client = await self._get_client()
            await client.upsert(
                collection_name=self._collection,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=query_embedding,
                        payload={
                            "silo_id": silo_id,
                            "doc_ids_hash": _doc_ids_hash(doc_ids),
                            "scores": scores_payload,
                            "query": query[:200],  # Truncate for debugging
                            "created_at": time.time(),
                        },
                    )
                ],
            )
            logger.debug("rerank_cache_set", silo_id=silo_id, doc_count=len(doc_ids))
        except Exception as e:
            logger.warning("rerank_cache_set_failed", error=str(e), silo_id=silo_id)


