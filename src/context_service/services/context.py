"""Context management service (thin slice)."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog
from primitives.schema.labels import ALL_CITE_LABELS

from context_service.config.settings import get_settings

# Re-export from hydration for timestamp parsing
from context_service.engine.hydration import _parse_dt
from context_service.services.models import (
    GraphResult,
    LookupResult,
    Node,
    QueryResult,
    ScopeContext,
    ScoredNode,
    derive_silo_id,
)
from context_service.signals import compute_freshness
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.embeddings.splade import SpladeEncoder
    from context_service.engine.history import BeliefHistory
    from context_service.engine.outbox import OutboxWriter
    from context_service.engine.protocols import HyperGraphStore
    from context_service.expansion.generator import ExpansionGenerator
    from context_service.services.auto_tagging import AutoTaggingService
    from context_service.services.context_meta import (
        HistoryResult,
        ProvenanceResult,
        ReasoningChainResult,
    )
    from context_service.stores import QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

MIN_CONTENT_FOR_EMBEDDING = 10

# node_type values accepted by store(). Drawn from primitives schema plus
# MetaObservation which is service-specific (not yet promoted to a primitives label).
_ALLOWED_NODE_TYPES: frozenset[str] = ALL_CITE_LABELS | frozenset({"MetaObservation"})

# Maps content_type strings from context_remember to proper Memgraph label names.
_CONTENT_TYPE_TO_LABEL: dict[str, str] = {
    "text": "Document",
    "utterance": "Utterance",
    "event": "Event",
}

# Properties written explicitly by CREATE — excluded from the SET n += $props pass
# to avoid overwriting with same or stale values.
_CREATE_PROPS: frozenset[str] = frozenset(
    {"id", "type", "content", "silo_id", "source_uri", "content_hash", "created_at"}
)


def _now_utc() -> datetime:
    """Indirection for testability — patched in tests to pin a fixed reference time."""
    return datetime.now(UTC)


def _format_timestamp(ts: Any) -> str | None:
    """Format a timestamp value to an ISO 8601 string."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return str(ts.isoformat())
    if isinstance(ts, (int, float)):
        # Memgraph timestamp() returns microseconds since epoch
        return datetime.fromtimestamp(ts / 1_000_000, tz=UTC).isoformat()
    return str(ts)


class ContextService:
    """Main entry point for context operations.

    Thin slice: store(), get(), lookup() only.
    Skipped for later: store_batch, store_chain, graph_traversal, link, delete,
    extraction, compaction.
    """

    def __init__(
        self,
        memgraph: HyperGraphStore,
        qdrant: QdrantClient,
        embedding: EmbeddingService | None = None,
        cache: RedisClient | None = None,
        splade: SpladeEncoder | None = None,
        expansion_generator: ExpansionGenerator | None = None,
        auto_tagging: AutoTaggingService | None = None,
        outbox: OutboxWriter | None = None,
    ) -> None:
        self._memgraph = memgraph
        self._qdrant = qdrant
        self._embedding = embedding
        self._cache = cache
        self._splade = splade
        self._expansion_generator = expansion_generator
        self._auto_tagging = auto_tagging
        self._outbox = outbox

    @property
    def graph_store(self) -> HyperGraphStore:
        """Expose the underlying HyperGraphStore for callers that need raw graph access."""
        return self._memgraph

    @property
    def embedding_client(self) -> EmbeddingService | None:
        """Expose the embedding service for callers that need it without accessing private state."""
        return self._embedding

    async def store(
        self,
        scope: ScopeContext,
        content: str,
        node_type: str,
        *,
        properties: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        source_uri: str | None = None,
        expansion: str | None = None,
    ) -> Node:
        """Store context node to Memgraph + Qdrant.

        Args:
            scope: Org and silo context.
            content: Text content to store.
            node_type: Node type label — must be in _ALLOWED_NODE_TYPES.
            properties: Optional metadata persisted to Memgraph via SET n += $props.
            idempotency_key: For deduplication.
            source_uri: Origin URI.
            expansion: Optional predicted-query expansion text stored as a
                Qdrant payload field for SPLADE encoding.

        Returns:
            Created or existing node.

        Raises:
            ValueError: If node_type is not in the allowed label set.
        """
        if node_type not in _ALLOWED_NODE_TYPES:
            raise ValueError(
                f"Unknown node_type {node_type!r}. Allowed: {sorted(_ALLOWED_NODE_TYPES)}"
            )

        silo_id = scope.silo_id
        cache_key = f"idempotency:{silo_id}:{idempotency_key}" if idempotency_key else None

        # Atomic idempotency: reserve the key with SET NX before any DB writes.
        # If another request wins the race, fetch its result instead.
        if cache_key and self._cache:
            existing_id = await self._cache.get(cache_key)
            if existing_id:
                try:
                    existing = await self.get(uuid.UUID(existing_id.decode()), silo_id)
                except ValueError:
                    # Corrupted cache entry — treat as a miss and proceed to write.
                    existing = None
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

        # Try to claim the idempotency key atomically BEFORE writing to DB.
        # If set_nx returns False, another concurrent request won — fetch its result.
        if cache_key and self._cache:
            claimed = await self._cache.set_nx(cache_key, str(node.id), ttl_seconds=86400)
            if not claimed:
                # Another request won the race — retry with exponential backoff
                # waiting for the winner to finish its DB write.
                _delays = [0.05, 0.1, 0.2, 0.4]
                winner: Node | None = None
                for _delay in _delays:
                    await asyncio.sleep(_delay)
                    winner_id = await self._cache.get(cache_key)
                    if winner_id:
                        try:
                            candidate = await self.get(uuid.UUID(winner_id.decode()), silo_id)
                        except ValueError:
                            candidate = None
                        if candidate:
                            winner = candidate
                            break
                if winner:
                    logger.debug("store_idempotent_race_lost", key=idempotency_key)
                    return winner

        # node_type is validated against _ALLOWED_NODE_TYPES above — f-string is safe.
        extra_props = {k: v for k, v in (properties or {}).items() if k not in _CREATE_PROPS}
        create_query = f"""
            CREATE (n:Node:{node_type} {{
                id: $id,
                type: $type,
                content: $content,
                silo_id: $silo_id,
                source_uri: $source_uri,
                content_hash: $content_hash,
                created_at: timestamp(),
                valid_from: $valid_from,
                heat_score: 0.0,
                tier: 'COLD',
                tags: []
            }})
            {"SET n += $extra_props" if extra_props else ""}
            RETURN n
        """
        params: dict[str, Any] = {
            "id": str(node.id),
            "type": node.type,
            "content": node.content,
            "silo_id": str(silo_id),
            "source_uri": source_uri or "",
            "content_hash": node.content_hash,
            "valid_from": datetime.now(UTC).isoformat(),
        }
        if extra_props:
            params["extra_props"] = extra_props

        await self._memgraph.execute_write(create_query, params)

        if content and len(content) >= MIN_CONTENT_FOR_EMBEDDING and self._embedding:
            vector = await self._embedding.embed_single(content)

            if self._auto_tagging is not None:
                try:
                    auto_tags = await self._auto_tagging.suggest_tags(
                        content_vector=vector,
                        silo_id=str(silo_id),
                    )
                except Exception as exc:
                    logger.warning(
                        "auto_tagging_failed_in_store",
                        node_id=str(node.id),
                        error=str(exc),
                    )
                    auto_tags = []

                if auto_tags:
                    user_tags: list[str] = list((properties or {}).get("tags") or [])
                    merged_tags = list(dict.fromkeys(user_tags + auto_tags))
                    tag_update_params: dict[str, Any] = {
                        "id": str(node.id),
                        "silo_id": str(silo_id),
                        "tags": merged_tags,
                        "auto_tags": auto_tags,
                    }
                    await self._memgraph.execute_write(
                        """
                        MATCH (n:Node {id: $id, silo_id: $silo_id})
                        SET n.tags = $tags, n.auto_tags = $auto_tags
                        """,
                        tag_update_params,
                    )
                    node.properties["tags"] = merged_tags
                    node.properties["auto_tags"] = auto_tags

            # Generate expansion for SPLADE if not already provided and generation is enabled.
            settings = get_settings()
            if (
                expansion is None
                and settings.expansion_generation_enabled
                and self._expansion_generator is not None
            ):
                try:
                    expansion = await self._expansion_generator.generate(content)
                except Exception as exc:
                    logger.warning(
                        "expansion_generation_failed_in_store",
                        node_id=str(node.id),
                        error=str(exc),
                    )
                    expansion = None

            sparse_indices: list[int] | None = None
            sparse_values: list[float] | None = None
            if self._splade is not None:
                # Concatenate expansion to content for SPLADE encoding only.
                # Dense embedding always uses the original content (unchanged).
                splade_input = content
                if expansion:
                    splade_input = content + " " + expansion
                try:
                    sparse = await self._splade.encode(splade_input)
                    sparse_indices, sparse_values = self._splade.to_qdrant(sparse)
                except Exception as exc:
                    logger.warning(
                        "splade_encode_failed_in_store",
                        node_id=str(node.id),
                        error=str(exc),
                    )

            outbox_metadata: dict[str, Any] = {
                "silo_id": str(silo_id),
                "node_type": node_type,
            }
            if sparse_indices is not None:
                outbox_metadata["sparse_indices"] = sparse_indices
            if sparse_values is not None:
                outbox_metadata["sparse_values"] = sparse_values
            if expansion is not None:
                outbox_metadata["expansion"] = expansion

            if self._outbox is not None:
                try:
                    await self._outbox.push(
                        {
                            "type": "embed",
                            "node_id": str(node.id),
                            "content": content,
                            "metadata": outbox_metadata,
                        }
                    )
                except Exception as exc:
                    logger.error(
                        "outbox_push_failed_falling_back_to_inline",
                        node_id=str(node.id),
                        silo_id=str(silo_id),
                        error=str(exc),
                    )
                    # Fall back to inline upsert so the node is still searchable.
                    await self._qdrant.upsert(
                        node_id=str(node.id),
                        vector=vector,
                        payload={"type": node_type},
                        silo_id=str(silo_id),
                        sparse_indices=sparse_indices,
                        sparse_values=sparse_values,
                        expansion=expansion,
                    )
            else:
                await self._qdrant.upsert(
                    node_id=str(node.id),
                    vector=vector,
                    payload={"type": node_type},
                    silo_id=str(silo_id),
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    expansion=expansion,
                )

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
                data = loads(cached)
                created_at_str = data.get("created_at")
                created_at = None
                if created_at_str:
                    from datetime import datetime

                    created_at = datetime.fromisoformat(created_at_str)
                return Node(
                    id=uuid.UUID(data["id"]),
                    type=data["type"],
                    content=data["content"],
                    properties=data.get("properties", {}),
                    silo_id=uuid.UUID(data["silo_id"]) if data.get("silo_id") else None,
                    source_uri=data.get("source_uri"),
                    content_hash=data.get("content_hash"),
                    created_at=created_at,
                )

        results = await self._memgraph.execute_query(
            """
            MATCH (n:Node {id: $id, silo_id: $silo_id})
            RETURN n.id AS id, n.type AS type, n.content AS content,
                   n.silo_id AS silo_id, n.source_uri AS source_uri,
                   n.content_hash AS content_hash, n.confidence AS confidence,
                   n.created_at AS created_at, labels(n) AS labels
            """,
            {"id": str(node_id), "silo_id": str(silo_id)},
        )

        if not results:
            return None

        row = results[0]
        labels = row.get("labels") or []
        node_type = row["type"]
        if not node_type and labels:
            non_node_labels = [lbl for lbl in labels if lbl != "Node"]
            node_type = non_node_labels[0] if non_node_labels else None
        raw_created_at = row.get("created_at")
        created_at = _parse_dt(raw_created_at) if raw_created_at is not None else None
        node = Node(
            id=uuid.UUID(row["id"]),
            type=node_type,
            content=row["content"],
            silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
            source_uri=row.get("source_uri"),
            content_hash=row.get("content_hash"),
            properties={
                "confidence": row.get("confidence"),
                "created_at": raw_created_at,
            },
            created_at=created_at,
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
                "properties": node.properties,
                "created_at": node.created_at.isoformat() if node.created_at else None,
            }
            await self._cache.set(cache_key, dumps(cache_data).encode())

        return node

    async def get_temporal(
        self,
        node_ids: list[uuid.UUID],
        silo_id: uuid.UUID,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch nodes by ID with temporal validity filtering.

        Args:
            node_ids: List of node UUIDs to fetch.
            silo_id: Silo to scope the lookup.
            as_of: Point-in-time for validity check (must be UTC).

        Returns:
            List of dicts, each either a full node or an error entry:
            - Valid node: {node_id, content, layer, ...}
            - not_yet_valid: {error, node_id, valid_from}
            - node_expired: {error, node_id, valid_to, superseded_by}
            - node_not_found: {error, node_id}
        """
        from context_service.db.queries import GET_NODES_BY_IDS_TEMPORAL

        rows = await self._memgraph.execute_query(
            GET_NODES_BY_IDS_TEMPORAL,
            {
                "node_ids": [str(nid) for nid in node_ids],
                "silo_id": str(silo_id),
            },
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            requested_id = row["requested_id"]
            node_id = row.get("node_id")

            # Node doesn't exist
            if node_id is None:
                results.append({"error": "node_not_found", "node_id": requested_id})
                continue

            # Uncommitted nodes treated as nonexistent
            if row.get("committed") is False:
                results.append({"error": "node_not_found", "node_id": requested_id})
                continue

            valid_from = row.get("valid_from")
            valid_to = row.get("valid_to")

            # Not yet valid: valid_from > as_of
            if valid_from is not None:
                vf = (
                    valid_from
                    if isinstance(valid_from, datetime)
                    else datetime.fromisoformat(str(valid_from).replace("Z", "+00:00"))
                )
                if vf > as_of:
                    results.append(
                        {
                            "error": "not_yet_valid",
                            "node_id": requested_id,
                            "valid_from": vf.isoformat(),
                        }
                    )
                    continue

            # Expired: valid_to <= as_of
            if valid_to is not None:
                vt = (
                    valid_to
                    if isinstance(valid_to, datetime)
                    else datetime.fromisoformat(str(valid_to).replace("Z", "+00:00"))
                )
                if vt <= as_of:
                    results.append(
                        {
                            "error": "node_expired",
                            "node_id": requested_id,
                            "valid_to": vt.isoformat(),
                            "superseded_by": row.get("superseded_by"),
                        }
                    )
                    continue

            # Valid node
            results.append(
                {
                    "node_id": node_id,
                    "content": row.get("content"),
                    "type": row.get("labels", ["Document"])[0] if row.get("labels") else "Document",
                    "layer": row.get("layer"),
                    "summary": row.get("summary"),
                    "confidence": row.get("confidence"),
                    "tags": row.get("tags"),
                    "source_uri": row.get("source_uri"),
                    "content_hash": row.get("content_hash"),
                    "valid_from": valid_from.isoformat()
                    if isinstance(valid_from, datetime)
                    else valid_from,
                    "valid_to": valid_to.isoformat()
                    if isinstance(valid_to, datetime)
                    else valid_to,
                    "created_at": (ca := row.get("created_at"))
                    and (ca.isoformat() if isinstance(ca, datetime) else ca),
                    "silo_id": str(silo_id),
                }
            )

        return results

    async def _batch_fetch_nodes(self, node_ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        """Fetch multiple nodes from cache then Memgraph for misses.

        Returns a mapping of node_id string -> Node.
        """
        result: dict[str, Node] = {}

        if self._cache:
            cache_keys = [f"node:{silo_id}:{nid}" for nid in node_ids]
            raw_values = await self._cache.mget(cache_keys)
            miss_ids: list[str] = []
            for nid, raw in zip(node_ids, raw_values, strict=True):
                if raw is not None:
                    try:
                        data = loads(raw)
                        created_at_str = data.get("created_at")
                        created_at_val = None
                        if created_at_str:
                            created_at_val = datetime.fromisoformat(created_at_str)
                        result[nid] = Node(
                            id=uuid.UUID(data["id"]),
                            type=data["type"],
                            content=data["content"],
                            properties=data.get("properties", {}),
                            silo_id=uuid.UUID(data["silo_id"]) if data.get("silo_id") else None,
                            source_uri=data.get("source_uri"),
                            content_hash=data.get("content_hash"),
                            created_at=created_at_val,
                        )
                    except (KeyError, ValueError):
                        miss_ids.append(nid)
                else:
                    miss_ids.append(nid)
        else:
            miss_ids = list(node_ids)

        if miss_ids:
            db_rows = await self._memgraph.execute_query(
                """
                UNWIND $ids AS id
                MATCH (n:Node {id: id, silo_id: $silo_id})
                RETURN n.id AS id, n.type AS type, n.content AS content,
                       n.silo_id AS silo_id, n.source_uri AS source_uri,
                       n.content_hash AS content_hash, n.created_at AS created_at,
                       n.tags AS tags, n.layer AS layer, n.confidence AS confidence,
                       n.summary AS summary, n.heat_score AS heat_score, n.tier AS tier
                """,
                {"ids": miss_ids, "silo_id": str(silo_id)},
            )
            for row in db_rows:
                created_at_val = row.get("created_at")
                if created_at_val is not None:
                    created_at_val = _parse_dt(created_at_val)
                props = {
                    "layer": row.get("layer", "memory"),
                    "tags": row.get("tags") or [],
                    "confidence": row.get("confidence", 1.0),
                    "summary": row.get("summary"),
                    "heat_score": row.get("heat_score"),
                    "tier": row.get("tier"),
                }
                node = Node(
                    id=uuid.UUID(row["id"]),
                    type=row["type"],
                    content=row["content"],
                    silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
                    source_uri=row.get("source_uri"),
                    content_hash=row.get("content_hash"),
                    created_at=created_at_val,
                    properties=props,
                )
                result[row["id"]] = node

            if self._cache and result:
                cache_mapping: dict[str, bytes] = {}
                for row_id, node in result.items():
                    if row_id not in miss_ids:
                        continue
                    n_created = node.created_at
                    cache_mapping[f"node:{silo_id}:{row_id}"] = dumps(
                        {
                            "id": str(node.id),
                            "type": node.type,
                            "content": node.content,
                            "silo_id": str(node.silo_id) if node.silo_id else None,
                            "source_uri": node.source_uri,
                            "content_hash": node.content_hash,
                            "created_at": n_created.isoformat() if n_created else None,
                            "properties": node.properties,
                        }
                    ).encode()
                if cache_mapping:
                    await self._cache.mset(cache_mapping)

        return result

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

        if not search_results:
            return LookupResult(
                nodes=[],
                silos_searched=silo_ids or [scope_silo_id],
                total_candidates=0,
                query=query,
            )

        result_ids = [r.node_id for r in search_results]
        node_map = await self._batch_fetch_nodes(result_ids, scope_silo_id)
        score_map = {r.node_id: r.score for r in search_results}

        scored_nodes: list[ScoredNode] = []
        for node_id_str in result_ids:
            node = node_map.get(node_id_str)
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
                    score=score_map[node_id_str],
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

    async def provenance(
        self,
        silo_id: str,
        node_id: str,
        max_depth: int = 10,  # noqa: ARG002
    ) -> ProvenanceResult:
        """Trace citation chain from node_id back to Memory-layer sources."""
        from context_service.db import queries as q
        from context_service.services.context_meta import ProvenanceResult, ProvenanceStep

        chain_rows, root_rows = await asyncio.gather(
            self._memgraph.execute_query(
                q.PROVENANCE_CHAIN,
                {"node_id": node_id, "silo_id": silo_id},
            ),
            self._memgraph.execute_query(
                q.PROVENANCE_ROOT_SOURCES,
                {"node_id": node_id, "silo_id": silo_id},
            ),
        )

        chain = [
            ProvenanceStep(
                node_id=r["node_id"],
                layer=r.get("layer") or "unknown",
                relationship=r.get("relationship") or "",
                confidence=float(r.get("confidence") or 1.0),
            )
            for r in chain_rows
        ]
        root_sources = [
            {
                "node_id": r["node_id"],
                "layer": r.get("layer") or "unknown",
                "content": r.get("content") or "",
                "confidence": float(r.get("confidence") or 1.0),
            }
            for r in root_rows
        ]

        return ProvenanceResult(chain=chain, root_sources=root_sources)

    async def history(
        self,
        silo_id: str,
        subject: str | None = None,
        node_id: str | None = None,
    ) -> HistoryResult:
        """Return belief evolution via SUPERSEDES chain."""
        from context_service.db import queries as q
        from context_service.services.context_meta import HistoryEntry, HistoryResult

        if node_id:
            rows, current_rows = await asyncio.gather(
                self._memgraph.execute_query(
                    q.BELIEF_HISTORY_BY_NODE,
                    {"node_id": node_id, "silo_id": silo_id},
                ),
                self._memgraph.execute_query(
                    q.BELIEF_HISTORY_CURRENT,
                    {"node_id": node_id, "silo_id": silo_id},
                ),
            )
        else:
            rows = await self._memgraph.execute_query(
                q.BELIEF_HISTORY_BY_SUBJECT,
                {"subject": subject, "silo_id": silo_id},
            )
            current_rows = rows[-1:] if rows else []

        timeline = [
            HistoryEntry(
                node_id=r["node_id"],
                content=r.get("content") or "",
                valid_from=r.get("valid_from"),
                valid_to=r.get("valid_to"),
                confidence=float(r.get("confidence") or 1.0),
                supersession_reason=r.get("supersession_reason"),
            )
            for r in rows
        ]

        current: dict[str, Any] | None = None
        if current_rows:
            cr = current_rows[0]
            current = {
                "node_id": cr.get("node_id") or node_id,
                "content": cr.get("content") or "",
                "confidence": float(cr.get("confidence") or 1.0),
                "superseded_by": cr.get("superseded_by"),
            }

        return HistoryResult(timeline=timeline, current=current)

    async def reason(
        self,
        silo_id: str,
        steps: list[Any],
        *,
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
        crystallizations: list[Any] | None = None,
        session_id: str,
        agent_id: str | None = None,
    ) -> ReasoningChainResult:
        """Store a reasoning chain to the Intelligence layer."""
        from context_service.services.context_meta import ReasoningChainResult

        chain_id = uuid.uuid4()
        steps_data = [
            {"step": s.step, "reasoning": s.reasoning, "confidence": s.confidence} for s in steps
        ]

        props: dict[str, Any] = {
            "layer": "intelligence",
            "session_id": session_id,
            "steps": dumps(steps_data),
            "steps_count": len(steps),
        }
        if conclusion:
            props["conclusion"] = conclusion
        if evidence_used:
            props["evidence_used"] = evidence_used
        if agent_id:
            props["agent_id"] = agent_id
        if crystallizations:
            props["crystallizations_count"] = len(crystallizations)

        content = conclusion or (steps[-1].reasoning if steps else "")

        await self._memgraph.execute_write(
            """
            MERGE (n:ReasoningChain {id: $id})
            ON CREATE SET
                n.silo_id = $silo_id,
                n.content = $content,
                n.layer = 'intelligence',
                n.session_id = $session_id,
                n.steps = $steps,
                n.steps_count = $steps_count,
                n.created_at = timestamp()
            ON MATCH SET
                n.content = $content,
                n.steps = $steps,
                n.steps_count = $steps_count
            """,
            {
                "id": str(chain_id),
                "silo_id": silo_id,
                "content": content,
                "session_id": session_id,
                "steps": dumps(steps_data),
                "steps_count": len(steps),
            },
        )

        if agent_id:
            await self._memgraph.execute_write(
                """
                MATCH (c {id: $chain_id})
                MERGE (a:Agent {id: $agent_id})
                MERGE (c)-[:REASONED_BY]->(a)
                """,
                {"chain_id": str(chain_id), "agent_id": agent_id},
            )

        return ReasoningChainResult(chain_id=chain_id)

    async def remember(
        self,
        scope: ScopeContext,
        content: str,
        content_type: str = "text",
        *,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: Any = None,
        observed_from: str | None = None,
        agent_id: str | None = None,
    ) -> Node:
        """Store to Memory layer with decay semantics."""
        from context_service.models.mcp import DecayClass

        if decay_class is None:
            decay_class = DecayClass.STANDARD

        props = dict(metadata or {})
        props["layer"] = "memory"
        props["decay_class"] = decay_class.value if hasattr(decay_class, "value") else decay_class
        props["content_type"] = content_type
        if tags:
            props["tags"] = tags
        if observed_from:
            props["observed_from"] = observed_from
        if agent_id:
            props["agent_id"] = agent_id

        label = _CONTENT_TYPE_TO_LABEL.get(content_type, content_type)
        return await self.store(
            scope=scope,
            content=content,
            node_type=label,
            properties=props,
        )

    async def assert_claim(
        self,
        scope: ScopeContext,
        claim: Any,
        evidence: list[str],
        source_type: Any,
        *,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent_id: str | None = None,
        source_tier: str | None = None,
    ) -> Node:
        """Assert a claim to Knowledge layer with evidence.

        ``source_tier`` (one of authoritative/validated/community/unknown) is
        persisted on the claim for downstream :Claim -> :Fact promotion via
        ``primitives.eag.epistemology``. Defaults to unknown if omitted.
        """
        from context_service.models.mcp import SPOClaim

        props = dict(metadata or {})
        props["layer"] = "knowledge"
        props["source_type"] = source_type.value if hasattr(source_type, "value") else source_type
        props["confidence"] = confidence
        props["evidence"] = evidence
        if source_tier is not None:
            props["source_tier"] = source_tier
        if tags:
            props["tags"] = tags
        if agent_id:
            props["agent_id"] = agent_id

        if isinstance(claim, SPOClaim):
            content = f"{claim.subject} {claim.predicate} {claim.object}"
            props["claim_structured"] = True
            props["subject"] = claim.subject
            props["predicate"] = claim.predicate
            props["object"] = claim.object
            if claim.qualifiers:
                props["qualifiers"] = claim.qualifiers
        else:
            content = claim

        node = await self.store(
            scope=scope,
            content=content,
            node_type="Claim",
            properties=props,
        )

        ev_node_ids = [ev_ref[5:] for ev_ref in evidence if ev_ref.startswith("node:")]
        if ev_node_ids:
            from context_service.db.queries import BATCH_CREATE_DERIVED_FROM_EDGES

            await self._memgraph.execute_write(
                BATCH_CREATE_DERIVED_FROM_EDGES,
                {
                    "claim_id": str(node.id),
                    "silo_id": str(scope.silo_id),
                    "ev_ids": ev_node_ids,
                },
            )

        return node

    async def promote_claim_to_fact(
        self,
        silo_id: str,
        claim_id: str,
        *,
        evidence_count: int | None = None,
        corroborations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Promote a :Claim to :Fact by creating a separate Fact node.

        Creates a new :Fact node with PROMOTED_FROM edge to the source :Claim.
        Returns the new Fact node properties on promotion, or None if the
        promotion was skipped (decision said no, or claim already has a Fact).
        """
        from context_service.custodian.fact_promotion import evaluate_claim_for_fact
        from context_service.db.queries import PROMOTE_CLAIM_TO_FACT

        if evidence_count is None:
            combined_rows = await self._memgraph.execute_query(
                "MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})"
                " OPTIONAL MATCH (c)-[:REFERENCES|DERIVED_FROM]->()"
                " RETURN properties(c) AS props, count(*) AS cnt",
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            if not combined_rows:
                return None
            claim_props: dict[str, Any] = dict(combined_rows[0]["props"])
            evidence_count = int(combined_rows[0]["cnt"])
        else:
            prop_rows = await self._memgraph.execute_query(
                "MATCH (c:Claim {id: $claim_id, silo_id: $silo_id}) RETURN properties(c) AS props",
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            if not prop_rows:
                return None
            claim_props = dict(prop_rows[0]["props"])

        decision = evaluate_claim_for_fact(claim_props, evidence_count, corroborations)
        if not decision.should_promote:
            return None

        rule_value: str = decision.rule.value if decision.rule is not None else ""
        fact_id = str(uuid.uuid4())

        promoted_rows = await self._memgraph.execute_write(
            PROMOTE_CLAIM_TO_FACT,
            {
                "claim_id": claim_id,
                "silo_id": silo_id,
                "rule": rule_value,
                "fact_id": fact_id,
            },
        )

        if not promoted_rows:
            # WHERE clause filtered it out — already has a Fact
            already_rows = await self._memgraph.execute_query(
                "MATCH (f:Fact)-[:PROMOTED_FROM]->(c:Claim {id: $claim_id, silo_id: $silo_id}) "
                "RETURN properties(f) AS props",
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            return dict(already_rows[0]["props"]) if already_rows else None

        logger.info(
            "claim_promoted_to_fact",
            claim_id=claim_id,
            fact_id=fact_id,
            silo_id=silo_id,
            rule=rule_value,
            evidence_count=evidence_count,
        )
        result_props: dict[str, Any] = dict(promoted_rows[0]["props"])
        return result_props

    async def commit_belief(
        self,
        scope: ScopeContext,
        belief: str,
        about: list[str],
        *,
        confidence: float = 0.8,
        reasoning: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent_id: str,
    ) -> Node:
        """Commit belief to Wisdom layer."""
        props = dict(metadata or {})
        props["layer"] = "wisdom"
        props["confidence"] = confidence
        props["about"] = about
        if reasoning:
            props["reasoning"] = reasoning
        if tags:
            props["tags"] = tags

        node = await self.store(
            scope=scope,
            content=belief,
            node_type="Commitment",
            properties=props,
        )

        await self._memgraph.execute_write(
            """
            MATCH (c {id: $commitment_id})
            MERGE (a:Agent {id: $agent_id})
            MERGE (c)-[:DECLARED_BY]->(a)
            """,
            {"commitment_id": str(node.id), "agent_id": agent_id},
        )

        if about:
            from context_service.db.queries import BATCH_CREATE_ABOUT_EDGES

            about_ids = [ref[5:] if ref.startswith("node:") else ref for ref in about]
            await self._memgraph.execute_write(
                BATCH_CREATE_ABOUT_EDGES,
                {
                    "src_id": str(node.id),
                    "silo_id": str(scope.silo_id),
                    "target_ids": about_ids,
                },
            )

        return node

    async def reflect(
        self,
        scope: ScopeContext,
        observation: str,
        observation_type: Any,
        about: list[str],
        *,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
        agent_id: str,
    ) -> Node:
        """Store a meta-observation (Meta-Memory layer).

        Supports hierarchical reflection: if targets include MetaObservations,
        the new observation's reflection_depth is max(target_depths) + 1.
        All MetaObservations have decay_class=permanent (they don't decay).
        """
        from context_service.db.queries import GET_META_OBSERVATION_DEPTHS

        props = dict(metadata or {})
        props["observation_type"] = (
            observation_type.value if hasattr(observation_type, "value") else observation_type
        )
        props["about"] = about
        props["confidence"] = confidence
        if agent_id:
            props["agent_id"] = agent_id

        # Compute reflection_depth for hierarchical meta-memory
        silo_id = str(scope.silo_id)
        if about:
            depth_records = await self._memgraph.execute_query(
                GET_META_OBSERVATION_DEPTHS,
                {"silo_id": silo_id, "target_ids": about},
            )
            target_depths = [r["reflection_depth"] for r in depth_records]
            props["reflection_depth"] = max(target_depths, default=0) + 1
        else:
            props["reflection_depth"] = 1

        # MetaObservations don't decay (per spec)
        props["decay_class"] = "permanent"

        node = await self.store(
            scope=scope,
            content=observation,
            node_type="MetaObservation",
            properties=props,
        )

        if about:
            from context_service.db.queries import BATCH_CREATE_ABOUT_EDGES

            await self._memgraph.execute_write(
                BATCH_CREATE_ABOUT_EDGES,
                {
                    "src_id": str(node.id),
                    "silo_id": str(scope.silo_id),
                    "target_ids": list(about),
                },
            )

        return node

    async def get_reflections(
        self,
        silo_id: str,
        node_id: str,
        *,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get MetaObservations about a node.

        Args:
            silo_id: Silo UUID.
            node_id: Target node ID.
            agent_id: Optional agent ID filter. When provided, only observations
                created by that agent are returned. Pass None (default) to
                return observations from all agents.

        Returns:
            List of reflection dicts with node_id, content, observation_type,
            confidence, agent_id, created_at.
        """
        from context_service.db.queries import GET_REFLECTIONS_FOR_NODE_BY_AGENT

        records = await self._memgraph.execute_query(
            GET_REFLECTIONS_FOR_NODE_BY_AGENT,
            {"node_id": node_id, "silo_id": silo_id, "agent_id": agent_id},
        )

        return [
            {
                "node_id": r["node_id"],
                "content": r["content"],
                "observation_type": r["observation_type"],
                "confidence": r["confidence"],
                "agent_id": r["agent_id"],
                "created_at": _format_timestamp(r["created_at"]),
            }
            for r in records
        ]

    async def query(
        self,
        scope: ScopeContext,
        query: str,
        *,
        layers: list[Any] | None = None,
        filters: Any | None = None,
        top_k: int = 10,
        include_superseded: bool = False,
        as_of: datetime | None = None,
        search_mode: Literal["hybrid", "dense", "sparse"] = "hybrid",
    ) -> list[QueryResult]:
        """Semantic search with layer filtering.

        Args:
            scope: Org and silo context.
            query: Search query text.
            layers: Optional layer filter list (Layer enum values).
            filters: Optional QueryFilters for metadata filtering.
            top_k: Maximum results.
            include_superseded: Include superseded nodes.
            as_of: Time-travel point (not yet implemented at store level).
            search_mode: Vector retrieval mode — ``"hybrid"`` (default),
                ``"dense"``, or ``"sparse"``. Hybrid requires a SPLADE encoder
                to be wired in; falls back to dense if not available.

        Returns:
            List of QueryResult ordered by relevance.
        """
        if not self._embedding:
            logger.warning("query_no_embedding_service")
            return []

        query_vector = await self._embedding.embed_query(query)

        sparse_indices: list[int] | None = None
        sparse_values: list[float] | None = None
        effective_mode = search_mode
        if search_mode in ("hybrid", "sparse") and self._splade is not None:
            try:
                sparse = await self._splade.encode_query(query)
                sparse_indices, sparse_values = self._splade.to_qdrant(sparse)
            except Exception as exc:
                logger.warning(
                    "splade_query_failed",
                    error=str(exc),
                    fallback="dense",
                )
                effective_mode = "dense"
        elif search_mode in ("hybrid", "sparse") and self._splade is None:
            logger.debug("splade_not_configured", fallback="dense")
            effective_mode = "dense"

        search_results = await self._qdrant.search(
            vector=query_vector,
            limit=top_k,
            silo_id=str(scope.silo_id),
            search_mode=effective_mode,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
        )

        if not search_results:
            return []

        result_ids = [r.node_id for r in search_results]
        score_map = {r.node_id: r.score for r in search_results}
        node_map = await self._batch_fetch_nodes(result_ids, scope.silo_id)

        layer_values: set[str] | None = None
        if layers:
            layer_values = {layer.value if hasattr(layer, "value") else layer for layer in layers}

        min_confidence: float | None = None
        tags_filter: list[str] | None = None
        if filters is not None:
            min_confidence = getattr(filters, "min_confidence", None)
            tags_filter = getattr(filters, "tags", None)

        settings = get_settings()
        freshness_weight = settings.freshness_weight
        sigma_days = settings.freshness_sigma_days
        now = _now_utc()

        results: list[QueryResult] = []
        for node_id_str in result_ids:
            node = node_map.get(node_id_str)
            if node is None:
                continue

            props = node.properties or {}
            node_layer = props.get("layer", "memory")

            if layer_values and node_layer not in layer_values:
                continue

            node_confidence = float(props.get("confidence") or 1.0)
            if min_confidence is not None and node_confidence < min_confidence:
                continue

            node_tags: list[str] = props.get("tags", [])
            if tags_filter and not any(t in node_tags for t in tags_filter):
                continue

            if not include_superseded and props.get("superseded_by"):
                continue

            if as_of is not None:
                valid_from = props.get("valid_from")
                valid_to = props.get("valid_to")
                if valid_from is not None:
                    vf = (
                        valid_from
                        if isinstance(valid_from, datetime)
                        else datetime.fromisoformat(str(valid_from))
                    )
                    if vf > as_of:
                        continue
                if valid_to is not None:
                    vt = (
                        valid_to
                        if isinstance(valid_to, datetime)
                        else datetime.fromisoformat(str(valid_to))
                    )
                    if vt <= as_of:
                        continue

            relevance = score_map[node_id_str]
            if freshness_weight > 0 and node.created_at is not None:
                fresh = compute_freshness(node.created_at, now, sigma_days=sigma_days)
                relevance = relevance * ((1.0 - freshness_weight) + freshness_weight * fresh)

            if settings.heat_ranking_enabled and settings.heat_weight > 0:
                raw_heat = props.get("heat_score")
                heat = float(raw_heat) if raw_heat is not None else 0.5
                relevance = relevance * ((1.0 - settings.heat_weight) + settings.heat_weight * heat)

            results.append(
                QueryResult(
                    node_id=node.id,
                    layer=node_layer,
                    content=node.content,
                    confidence=node_confidence,
                    relevance_score=relevance,
                    summary=props.get("summary"),
                    tags=node_tags or None,
                    created_at=node.created_at,
                )
            )

        # Re-sort: freshness multiplier mutates relevance_score, so the original
        # Qdrant order no longer reflects final ranking. Callers see freshness-
        # adjusted ordering when freshness_weight > 0; identical to Qdrant order
        # when freshness_weight == 0.
        results.sort(key=lambda r: r.relevance_score, reverse=True)

        logger.info(
            "query_complete",
            query_len=len(query),
            result_count=len(results),
            silo_id=str(scope.silo_id),
        )
        return results

    async def temporal_query(
        self,
        silo_id: str,
        as_of: datetime,
        query: str,
        top_k: int = 10,
        type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Memgraph temporal query: return nodes valid at as_of timestamp.

        When ``query`` is non-empty and an embedding service is configured,
        Qdrant is used to pre-filter candidate node IDs (top ``3 * top_k`` by
        vector similarity). Memgraph then filters to those candidates and
        orders by ``valid_from DESC``. Qdrant ranking is discarded; recency
        governs final order.

        When ``query`` is empty or no embedding service is wired, falls back
        to a full temporal scan (original behavior).
        """
        from context_service.db.queries import TEMPORAL_QUERY, TEMPORAL_QUERY_FILTERED

        use_semantic_filter = bool(query) and self._embedding is not None

        if use_semantic_filter:
            embedding = cast("EmbeddingService", self._embedding)
            query_vector = await embedding.embed_query(query)
            qdrant_results = await self._qdrant.search(
                vector=query_vector,
                limit=3 * top_k,
                silo_id=silo_id,
                search_mode="dense",
            )
            candidate_ids = [r.node_id for r in qdrant_results]
            if not candidate_ids:
                return []
            cypher = TEMPORAL_QUERY_FILTERED
            params: dict[str, Any] = {
                "silo_id": silo_id,
                "candidate_ids": candidate_ids,
                "as_of": as_of.isoformat(),
                "type_filter": type_filter,
                "limit": top_k,
            }
        else:
            cypher = TEMPORAL_QUERY
            params = {
                "silo_id": silo_id,
                "as_of": as_of.isoformat(),
                "type_filter": type_filter,
                "limit": top_k,
            }

        rows = await self._memgraph.execute_query(cypher, params)

        results = []
        for row in rows:
            results.append(
                {
                    "node_id": row["id"],
                    "content": row["content"],
                    "labels": row["labels"],
                    "confidence": row.get("confidence"),
                    "valid_from": _format_timestamp(row.get("valid_from")),
                    "valid_to": _format_timestamp(row.get("valid_to")),
                    "created_at": _format_timestamp(row.get("created_at")),
                }
            )
        return results

    async def link(
        self,
        silo_id: str,
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
    ) -> str:
        """Create a typed relationship between two nodes.

        Args:
            silo_id: Silo UUID string for scoping.
            from_node: Source node ID.
            to_node: Target node ID.
            relationship: Relationship type label (e.g. REFERENCES).
            weight: Edge weight.
            note: Optional annotation.

        Returns:
            Generated edge ID string.

        Raises:
            ValueError: If ``relationship`` is not a member of
                ``models.mcp.RelationshipType``. Defense-in-depth so non-MCP
                callers (services, tests, future APIs) cannot inject Cypher.
        """
        from context_service.models.mcp import RelationshipType

        try:
            rel_type = RelationshipType(relationship).value
        except ValueError as exc:
            raise ValueError(
                f"Invalid relationship {relationship!r}; "
                f"must be one of {[e.value for e in RelationshipType]}"
            ) from exc

        edge_id = str(uuid.uuid4())
        props: dict[str, Any] = {"id": edge_id, "weight": weight}
        if note:
            props["note"] = note

        await self._memgraph.execute_write(
            f"""
            MATCH (a {{id: $from_id, silo_id: $silo_id}})
            MATCH (b {{id: $to_id, silo_id: $silo_id}})
            CREATE (a)-[r:{rel_type} $props]->(b)
            """,
            {"from_id": from_node, "to_id": to_node, "silo_id": silo_id, "props": props},
        )

        logger.info(
            "link_created",
            edge_id=edge_id,
            from_node=from_node,
            to_node=to_node,
            relationship=relationship,
        )
        return edge_id

    async def graph_traversal(
        self,
        silo_id: str,
        *,
        query: str | None = None,
        seed_nodes: list[str] | None = None,
        max_depth: int = 2,
        max_nodes: int = 50,
        relationship_types: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> GraphResult:
        """Graph traversal from semantic seed or explicit nodes.

        Args:
            silo_id: Silo UUID string.
            query: Semantic seed query (requires embedding service).
            seed_nodes: Explicit starting node IDs.
            max_depth: Maximum traversal depth.
            max_nodes: Maximum nodes to return.
            relationship_types: Filter to specific relationship labels.
            layers: Filter to specific layers.

        Returns:
            GraphResult with nodes, edges, and traversal stats.
        """
        start_ids: list[str] = list(seed_nodes or [])

        if query and self._embedding:
            query_vector = await self._embedding.embed_query(query)
            search_results = await self._qdrant.search(
                vector=query_vector,
                limit=5,
                silo_id=silo_id,
            )
            start_ids = [r.node_id for r in search_results] + start_ids

        if not start_ids:
            return GraphResult(
                nodes=[], edges=[], depth_reached=0, nodes_visited=0, edges_traversed=0
            )

        layer_filter = ""
        if layers:
            quoted = ", ".join(f'"{lyr}"' for lyr in layers)
            layer_filter = f"AND n.layer IN [{quoted}]"

        if not isinstance(max_depth, int):
            raise TypeError(f"max_depth must be an int, got {type(max_depth).__name__!r}")

        rows = await self._memgraph.execute_query(
            f"""
            UNWIND $start_ids AS seed_id
            MATCH (seed {{id: seed_id, silo_id: $silo_id}})
            OPTIONAL MATCH path = (seed)-[*1..{max_depth}]-(neighbor)
            WHERE neighbor.silo_id = $silo_id {layer_filter}
            WITH seed, [x IN COLLECT(DISTINCT neighbor) WHERE x IS NOT NULL] AS neighbors
            WITH [seed] + neighbors AS all_nodes
            UNWIND all_nodes AS n
            RETURN DISTINCT
                n.id AS node_id,
                n.type AS type,
                n.content AS content,
                COALESCE(n.layer, 'memory') AS layer,
                n.confidence AS confidence
            LIMIT $max_nodes
            """,
            {"start_ids": start_ids, "silo_id": silo_id, "max_nodes": max_nodes},
        )

        edge_rows: list[dict[str, Any]] = []
        if rows:
            node_ids_found = [r["node_id"] for r in rows if r.get("node_id")]
            if len(node_ids_found) > 1:
                params: dict[str, Any] = {"node_ids": node_ids_found}
                rel_filter = ""
                if relationship_types:
                    rel_filter = "AND type(r) IN $rel_types"
                    params["rel_types"] = list(relationship_types)
                edge_rows = await self._memgraph.execute_query(
                    f"""
                    UNWIND $node_ids AS nid
                    MATCH (a {{id: nid}})-[r]->(b)
                    WHERE b.id IN $node_ids {rel_filter}
                    RETURN a.id AS from_node, b.id AS to_node, type(r) AS relationship,
                           COALESCE(r.weight, 1.0) AS weight,
                           COALESCE(r.inferred, false) AS inferred
                    """,
                    params,
                )

        nodes_out = [
            {
                "node_id": r["node_id"],
                "type": r.get("type", "context"),
                "content": r.get("content", ""),
                "layer": r.get("layer", "memory"),
                "confidence": r.get("confidence"),
            }
            for r in rows
            if r.get("node_id")
        ]

        edges_out = [
            {
                "from_node": e["from_node"],
                "to_node": e["to_node"],
                "relationship": e["relationship"],
                "weight": e.get("weight", 1.0),
                "inferred": bool(e.get("inferred", False)),
            }
            for e in edge_rows
        ]

        logger.info(
            "graph_traversal_complete",
            nodes=len(nodes_out),
            edges=len(edges_out),
            silo_id=silo_id,
        )

        return GraphResult(
            nodes=nodes_out,
            edges=edges_out,
            depth_reached=max_depth,
            nodes_visited=len(nodes_out),
            edges_traversed=len(edges_out),
        )

    async def belief_history(
        self,
        silo_id: str,
        node_id: str,
        limit: int = 20,
    ) -> BeliefHistory:
        """Return the supersession chain for a fact node.

        Wraps ``engine.history.get_belief_history`` so callers use the service
        protocol rather than accessing ``_memgraph`` directly.

        Args:
            silo_id: Silo UUID string for scoping.
            node_id: Starting fact node ID.
            limit: Maximum chain length to traverse.

        Returns:
            BeliefHistory dataclass.
        """
        from context_service.engine.history import get_belief_history

        return await get_belief_history(
            memgraph=self._memgraph,
            silo_id=silo_id,
            start_id=node_id,
            limit=limit,
        )
