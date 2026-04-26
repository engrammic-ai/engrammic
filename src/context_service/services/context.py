"""Context management service (thin slice)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from context_service.services.models import (
    LookupResult,
    Node,
    ScopeContext,
    ScoredNode,
    derive_silo_id,
)

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.stores import MemgraphClient, QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

MIN_CONTENT_FOR_EMBEDDING = 10


class ContextService:
    """Main entry point for context operations.

    Thin slice: store(), get(), lookup() only.
    Skipped for later: store_batch, store_chain, graph_traversal, link, delete,
    extraction, compaction.
    """

    def __init__(
        self,
        memgraph: MemgraphClient,
        qdrant: QdrantClient,
        embedding: EmbeddingService | None = None,
        cache: RedisClient | None = None,
    ) -> None:
        self._memgraph = memgraph
        self._qdrant = qdrant
        self._embedding = embedding
        self._cache = cache

    async def store(
        self,
        scope: ScopeContext,
        content: str,
        node_type: str,
        *,
        properties: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        source_uri: str | None = None,
    ) -> Node:
        """Store context node to Memgraph + Qdrant.

        Args:
            scope: Org and silo context.
            content: Text content to store.
            node_type: Node type label.
            properties: Optional metadata.
            idempotency_key: For deduplication.
            source_uri: Origin URI.

        Returns:
            Created or existing node.
        """
        silo_id = scope.silo_id

        if idempotency_key and self._cache:
            cache_key = f"idempotency:{silo_id}:{idempotency_key}"
            existing_id = await self._cache.get(cache_key)
            if existing_id:
                existing = await self.get(uuid.UUID(existing_id.decode()), silo_id)
                if existing:
                    logger.debug("store_idempotent_hit", key=idempotency_key)
                    return existing

        node = Node(
            id=uuid.uuid4(),
            type=node_type,
            content=content,
            properties=properties or {},
            silo_id=silo_id,
            source_uri=source_uri,
            content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
        )

        await self._memgraph.execute_write(
            """
            CREATE (n:Node {
                id: $id,
                type: $type,
                content: $content,
                silo_id: $silo_id,
                source_uri: $source_uri,
                content_hash: $content_hash,
                created_at: timestamp()
            })
            RETURN n
            """,
            {
                "id": str(node.id),
                "type": node.type,
                "content": node.content,
                "silo_id": str(silo_id),
                "source_uri": source_uri or "",
                "content_hash": node.content_hash,
            },
        )

        if content and len(content) >= MIN_CONTENT_FOR_EMBEDDING and self._embedding:
            try:
                vector = await self._embedding.embed_single(content)
                await self._qdrant.upsert(
                    node_id=str(node.id),
                    vector=vector,
                    payload={"type": node_type},
                    silo_id=str(silo_id),
                )
            except Exception:
                logger.warning("store_embedding_failed", node_id=str(node.id), exc_info=True)

        if idempotency_key and self._cache:
            cache_key = f"idempotency:{silo_id}:{idempotency_key}"
            await self._cache.set(cache_key, str(node.id).encode(), ttl_seconds=86400)

        logger.info("context_stored", node_id=str(node.id), type=node_type, silo_id=str(silo_id))
        return node

    async def get(self, node_id: uuid.UUID, silo_id: uuid.UUID) -> Node | None:
        """Fetch a single node by ID.

        Args:
            node_id: Node UUID.
            silo_id: Silo UUID for scoping.

        Returns:
            Node if found, None otherwise.
        """
        if self._cache:
            cache_key = f"node:{silo_id}:{node_id}"
            cached = await self._cache.get(cache_key)
            if cached:
                data = json.loads(cached)
                return Node(
                    id=uuid.UUID(data["id"]),
                    type=data["type"],
                    content=data["content"],
                    properties=data.get("properties", {}),
                    silo_id=uuid.UUID(data["silo_id"]) if data.get("silo_id") else None,
                    source_uri=data.get("source_uri"),
                    content_hash=data.get("content_hash"),
                )

        results = await self._memgraph.execute_query(
            """
            MATCH (n:Node {id: $id, silo_id: $silo_id})
            RETURN n.id AS id, n.type AS type, n.content AS content,
                   n.silo_id AS silo_id, n.source_uri AS source_uri,
                   n.content_hash AS content_hash
            """,
            {"id": str(node_id), "silo_id": str(silo_id)},
        )

        if not results:
            return None

        row = results[0]
        node = Node(
            id=uuid.UUID(row["id"]),
            type=row["type"],
            content=row["content"],
            silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
            source_uri=row.get("source_uri"),
            content_hash=row.get("content_hash"),
        )

        if self._cache:
            cache_key = f"node:{silo_id}:{node_id}"
            cache_data = {
                "id": str(node.id),
                "type": node.type,
                "content": node.content,
                "silo_id": str(node.silo_id) if node.silo_id else None,
                "source_uri": node.source_uri,
                "content_hash": node.content_hash,
            }
            await self._cache.set(cache_key, json.dumps(cache_data).encode())

        return node

    async def lookup(
        self,
        query: str,
        org_id: str,
        *,
        silo_ids: list[uuid.UUID] | None = None,
        max_nodes: int = 50,
        type_filter: str | None = None,
    ) -> LookupResult:
        """Semantic search for context nodes.

        Args:
            query: Search query text.
            org_id: Organization ID.
            silo_ids: Optional list of silos to search.
            max_nodes: Maximum results.
            type_filter: Filter by node type.

        Returns:
            LookupResult with scored nodes.
        """
        scope_silo_id = derive_silo_id(org_id)

        if not self._embedding:
            logger.warning("lookup_no_embedding_service")
            return LookupResult(
                nodes=[],
                silos_searched=silo_ids or [],
                total_candidates=0,
                query=query,
            )

        query_vector = await self._embedding.embed_query(query)

        search_results = await self._qdrant.search(
            vector=query_vector,
            limit=max_nodes,
            silo_id=str(scope_silo_id),
        )

        scored_nodes: list[ScoredNode] = []
        for result in search_results:
            node = await self.get(uuid.UUID(result.node_id), scope_silo_id)
            if node is None:
                continue
            if type_filter and node.type != type_filter:
                continue

            scored_nodes.append(
                ScoredNode(
                    node_id=node.id,
                    content=node.content,
                    type=node.type,
                    silo_id=node.silo_id or scope_silo_id,
                    score=result.score,
                    properties=node.properties,
                )
            )

        logger.info(
            "lookup_complete",
            query_len=len(query),
            result_count=len(scored_nodes),
            org_id=org_id,
        )

        return LookupResult(
            nodes=scored_nodes,
            silos_searched=silo_ids or [scope_silo_id],
            total_candidates=len(search_results),
            query=query,
        )
