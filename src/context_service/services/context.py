"""Context management service (thin slice)."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog
from primitives.schema import ALL_CITE_LABELS

from context_service.config.settings import get_settings
from context_service.engine.epistemics import CONFIDENCE_FORMULA_VERSION, effective_confidence
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
    from context_service.embeddings.sparse import SparseEncoder
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

# Knowledge-layer node types that trigger Custodian identity
_KNOWLEDGE_LAYER_TYPES: frozenset[str] = frozenset({"Fact", "Claim", "Commitment"})

# Module-level singleton for Custodian trigger
_custodian_trigger: Any = None


def _get_custodian_trigger() -> Any:
    global _custodian_trigger
    if _custodian_trigger is None:
        settings = get_settings()
        from context_service.custodian.identities.custodian import on_custodian_batch_fire
        from context_service.custodian.identities.triggers.async_batch import AsyncBatchTrigger

        _custodian_trigger = AsyncBatchTrigger(
            batch_size=settings.identities.custodian.batch_size,
            window_seconds=settings.identities.custodian.batch_window_seconds,
            on_fire=on_custodian_batch_fire,
        )
    return _custodian_trigger


# node_type values accepted by store(). Drawn from primitives schema labels.
_ALLOWED_NODE_TYPES: frozenset[str] = ALL_CITE_LABELS

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
        sparse: SparseEncoder | None = None,
        expansion_generator: ExpansionGenerator | None = None,
        auto_tagging: AutoTaggingService | None = None,
    ) -> None:
        self._memgraph = memgraph
        self._qdrant = qdrant
        self._embedding = embedding
        self._cache = cache
        self._sparse = sparse
        self._expansion_generator = expansion_generator
        self._auto_tagging = auto_tagging

    @property
    def graph_store(self) -> HyperGraphStore:
        """Expose the underlying HyperGraphStore for callers that need raw graph access."""
        return self._memgraph

    @property
    def embedding_client(self) -> EmbeddingService | None:
        """Expose the embedding service for callers that need it without accessing private state."""
        return self._embedding

    @property
    def vector_store(self) -> QdrantClient:
        """Expose the Qdrant client for callers that need direct vector operations."""
        return self._qdrant

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
        content_hash: str | None = None,
        extra_labels: list[str] | None = None,
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
            content_hash: Pre-computed SHA256 hash. If None, computed from content.
            extra_labels: Optional additional Cypher labels to attach beyond
                ``Node:{node_type}``. Each entry must be a valid label name
                (alphanumeric/underscore). Use this to apply dual-label
                semantics required by Cypher queries (e.g. ``["Claim"]`` for
                Commitment nodes so custodian Cypher finds them via ``:Claim``).

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
            content_hash=content_hash or hashlib.sha256(content.encode()).hexdigest(),
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
        # extra_labels entries are alphanumeric/underscore only (no user-supplied
        # values reach this point without validation at the call site).
        extra_label_str = "".join(f":{lbl}" for lbl in (extra_labels or []))
        extra_props = {k: v for k, v in (properties or {}).items() if k not in _CREATE_PROPS}
        create_query = f"""
            CREATE (n:Node:{node_type}{extra_label_str} {{
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
                tags: [],
                committed: true
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
            if self._sparse is not None:
                # Concatenate expansion to content for SPLADE encoding only.
                # Dense embedding always uses the original content (unchanged).
                splade_input = content
                if expansion:
                    splade_input = content + " " + expansion
                try:
                    sparse = await self._sparse.encode(splade_input)
                    sparse_indices, sparse_values = self._sparse.to_qdrant(sparse)
                except Exception as exc:
                    logger.warning(
                        "splade_encode_failed_in_store",
                        node_id=str(node.id),
                        error=str(exc),
                    )

            try:
                await self._qdrant.upsert(
                    node_id=str(node.id),
                    vector=vector,
                    payload={"type": node_type},
                    silo_id=str(silo_id),
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    expansion=expansion,
                )
            except Exception as exc:
                logger.error(
                    "qdrant_upsert_failed_rolling_back_memgraph",
                    node_id=str(node.id),
                    silo_id=str(silo_id),
                    error=str(exc),
                )
                from context_service.engine.queries import DELETE_NODE

                try:
                    await self._memgraph.execute_write(
                        DELETE_NODE,
                        {"id": str(node.id), "silo_id": str(silo_id)},
                    )
                except Exception as rollback_exc:
                    logger.error(
                        "memgraph_rollback_failed",
                        node_id=str(node.id),
                        silo_id=str(silo_id),
                        error=str(rollback_exc),
                    )
                raise

        logger.info("context_stored", node_id=str(node.id), type=node_type, silo_id=str(silo_id))

        # Fire Custodian identity on Knowledge-layer writes
        if node_type in _KNOWLEDGE_LAYER_TYPES:
            settings = get_settings()
            if settings.identities.custodian.enabled:
                trigger = _get_custodian_trigger()
                asyncio.create_task(trigger.enqueue(str(silo_id), str(node.id), "store"))

            # Bump knowledge version to invalidate result cache
            if self._cache is not None:
                asyncio.create_task(self._cache.incr(f"silo:{silo_id}:knowledge_version"))

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
                   n.content_hash AS content_hash, n.created_at AS created_at,
                   labels(n) AS labels, properties(n) AS props
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
        if isinstance(raw_created_at, str):
            from datetime import datetime

            created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
        elif isinstance(raw_created_at, int):
            from datetime import UTC, datetime

            created_at = datetime.fromtimestamp(raw_created_at / 1_000_000, tz=UTC)
        else:
            created_at = raw_created_at
        all_props = row.get("props") or {}
        node = Node(
            id=uuid.UUID(row["id"]),
            type=node_type,
            content=row["content"],
            silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
            source_uri=row.get("source_uri"),
            content_hash=row.get("content_hash"),
            properties=all_props,
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
                WHERE n.tombstoned_at IS NULL
                RETURN n.id AS id, n.type AS type, n.content AS content,
                       n.silo_id AS silo_id, n.source_uri AS source_uri,
                       n.content_hash AS content_hash, n.created_at AS created_at,
                       n.tags AS tags, n.layer AS layer, n.confidence AS confidence,
                       n.summary AS summary, n.heat_score AS heat_score, n.tier AS tier,
                       n.effective_heat AS effective_heat
                """,
                {"ids": miss_ids, "silo_id": str(silo_id)},
            )
            for row in db_rows:
                created_at_val = row.get("created_at")
                if created_at_val is not None:
                    if isinstance(created_at_val, int):
                        created_at_val = datetime.fromtimestamp(created_at_val / 1_000_000, tz=UTC)
                    elif isinstance(created_at_val, str):
                        created_at_val = datetime.fromisoformat(
                            created_at_val.replace("Z", "+00:00")
                        )
                props = {
                    "layer": row.get("layer", "memory"),
                    "tags": row.get("tags") or [],
                    "confidence": effective_confidence(row),
                    "summary": row.get("summary"),
                    "heat_score": row.get("heat_score"),
                    "effective_heat": row.get("effective_heat"),
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
        max_depth: int = 5,
        direction: Literal["up", "down"] = "up",
        edge_types: list[str] | None = None,
    ) -> ProvenanceResult:
        """Trace citation chain from node_id.

        Args:
            silo_id: Silo scope.
            node_id: Node to trace.
            max_depth: Maximum traversal depth (default 5).
            direction: "up" traces to sources (provenance), "down" traces to
                derived nodes (impact analysis).
            edge_types: Filter to specific edge types. Valid values:
                DERIVED_FROM, PROMOTED_FROM, SYNTHESIZED_FROM, REFERENCES.
                None means all edge types.
        """
        from context_service.db import queries as q
        from context_service.services.context_meta import ProvenanceResult, ProvenanceStep

        if direction == "up":
            chain_query = q.build_provenance_chain_query(max_depth)
            leaf_query = q.build_provenance_root_sources_query(max_depth)
        else:
            chain_query = q.build_impact_chain_query(max_depth)
            leaf_query = q.build_impact_leaf_nodes_query(max_depth)

        chain_rows, leaf_rows = await asyncio.gather(
            self._memgraph.execute_query(
                chain_query,
                {"node_id": node_id, "silo_id": silo_id},
            ),
            self._memgraph.execute_query(
                leaf_query,
                {"node_id": node_id, "silo_id": silo_id},
            ),
        )

        # Filter by edge_types if specified
        if edge_types:
            edge_set = set(edge_types)
            chain_rows = [
                r
                for r in chain_rows
                if r.get("relationship") in edge_set or r.get("relationship") is None
            ]

        chain = [
            ProvenanceStep(
                node_id=r["node_id"],
                layer=r.get("layer") or "unknown",
                relationship=r.get("relationship") or "",
                confidence=effective_confidence(r),
                stub=bool(r.get("stub") or False),
            )
            for r in chain_rows
        ]
        leaf_nodes = [
            {
                "node_id": r["node_id"],
                "layer": r.get("layer") or "unknown",
                "content": r.get("content") or "",
                "confidence": effective_confidence(r),
            }
            for r in leaf_rows
        ]

        return ProvenanceResult(chain=chain, root_sources=leaf_nodes)

    async def history(
        self,
        silo_id: str,
        subject: str | None = None,
        node_id: str | None = None,
    ) -> HistoryResult:
        """Return belief evolution via SUPERSEDES chain.

        Uses bidirectional traversal to find the full chain regardless of
        which node in the chain is queried. Timeline is ordered oldest to newest.
        """
        from context_service.db import queries as q
        from context_service.services.context_meta import HistoryEntry, HistoryResult

        if node_id:
            rows = await self._memgraph.execute_query(
                q.BELIEF_HISTORY_BIDIRECTIONAL,
                {"node_id": node_id, "silo_id": silo_id},
            )
        else:
            rows = await self._memgraph.execute_query(
                q.BELIEF_HISTORY_BY_SUBJECT,
                {"subject": subject, "silo_id": silo_id},
            )

        timeline = [
            HistoryEntry(
                node_id=r["node_id"],
                content=r.get("content") or "",
                valid_from=r.get("valid_from"),
                valid_to=r.get("valid_to"),
                confidence=effective_confidence(r),
                supersession_reason=r.get("supersession_reason"),
            )
            for r in rows
        ]

        return HistoryResult(timeline=timeline, current=None)

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

        The stored confidence is computed via ``partial_confidence`` which
        applies a 0.7 epistemic discount for uncorroborated single-source
        claims. Source tier maps to source_reliability weight.

        After storage, runs conflict detection for SPO claims and updates
        corroboration count for all claims.
        """
        from primitives.eag.epistemology import SourceTier, partial_confidence

        from context_service.models.mcp import SPOClaim
        from context_service.sage import (
            check_corroboration,
            compute_credibility,
            detect_spo_conflict,
        )

        tier = SourceTier(source_tier) if source_tier else SourceTier.UNKNOWN
        discounted_confidence = partial_confidence(confidence, source_reliability=tier.weight)

        # Compute credibility with full breakdown
        credibility_breakdown = compute_credibility(
            source_tier=source_tier,
            method=metadata.get("extraction_method") if metadata else None,
            raw_confidence=confidence,
        )

        props = dict(metadata or {})
        props["layer"] = "knowledge"
        props["source_type"] = source_type.value if hasattr(source_type, "value") else source_type
        props["confidence"] = discounted_confidence
        props["raw_confidence"] = confidence
        props["confidence_formula_version"] = CONFIDENCE_FORMULA_VERSION
        props["evidence"] = evidence
        props["credibility"] = credibility_breakdown.credibility
        props["credibility_factors"] = credibility_breakdown.to_dict()
        props["conflict_status"] = "none"
        if source_tier is not None:
            props["source_tier"] = source_tier
        if tags:
            props["tags"] = tags
        if agent_id:
            props["agent_id"] = agent_id

        # Track SPO for conflict detection
        subject: str | None = None
        predicate: str | None = None
        object_value: str | None = None

        if isinstance(claim, SPOClaim):
            content = f"{claim.subject} {claim.predicate} {claim.object}"
            props["claim_structured"] = True
            props["subject"] = claim.subject
            props["predicate"] = claim.predicate
            props["object"] = claim.object
            subject = claim.subject
            predicate = claim.predicate
            object_value = claim.object
            if claim.qualifiers:
                props["qualifiers"] = claim.qualifiers
        else:
            content = claim

        # Content-hash deduplication: return existing claim if identical content exists
        claim_hash = hashlib.sha256(content.encode()).hexdigest()
        existing_rows = await self._memgraph.execute_query(
            """
            MATCH (c:Claim {silo_id: $silo_id, content_hash: $content_hash})
            WHERE c.tombstoned_at IS NULL
            RETURN c.id AS id, c.type AS type, c.content AS content,
                   c.silo_id AS silo_id, c.source_uri AS source_uri,
                   c.content_hash AS content_hash, c.created_at AS created_at,
                   c.properties AS properties
            LIMIT 1
            """,
            {"silo_id": str(scope.silo_id), "content_hash": claim_hash},
        )

        if existing_rows:
            row = existing_rows[0]
            logger.debug("assert_claim_content_hash_hit", content_hash=claim_hash)
            raw_props = row.get("properties")
            if raw_props is None:
                props_existing = {}
            elif isinstance(raw_props, str):
                props_existing = loads(raw_props)
            else:
                props_existing = raw_props
            existing_node = Node(
                id=uuid.UUID(row["id"]),
                type=row["type"],
                content=row["content"],
                properties=props_existing,
                silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
                source_uri=row.get("source_uri"),
                content_hash=row.get("content_hash"),
            )

            # Still create evidence edges to accumulate corroboration
            ev_node_ids = [ev_ref[5:] for ev_ref in evidence if ev_ref.startswith("node:")]
            if ev_node_ids:
                from context_service.db.queries import BATCH_CREATE_DERIVED_FROM_EDGES

                await self._memgraph.execute_write(
                    BATCH_CREATE_DERIVED_FROM_EDGES,
                    {
                        "claim_id": str(existing_node.id),
                        "silo_id": str(scope.silo_id),
                        "ev_ids": ev_node_ids,
                    },
                )

            return existing_node

        node = await self.store(
            scope=scope,
            content=content,
            node_type="Claim",
            properties=props,
            content_hash=claim_hash,
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

        # Conflict detection for SPO claims
        conflict_events = await detect_spo_conflict(
            store=self._memgraph,
            new_node_id=str(node.id),
            subject=subject,
            predicate=predicate,
            object_value=object_value,
            silo_id=str(scope.silo_id),
        )
        if conflict_events:
            logger.info(
                "claim_conflicts_detected",
                node_id=str(node.id),
                conflict_count=len(conflict_events),
            )

        # Check corroboration (updates corroboration_count on matching claims)
        corroboration_count, should_promote = await check_corroboration(
            store=self._memgraph,
            node_id=str(node.id),
            silo_id=str(scope.silo_id),
        )
        if corroboration_count > 1:
            logger.debug(
                "claim_corroboration_updated",
                node_id=str(node.id),
                corroboration_count=corroboration_count,
                should_promote=should_promote,
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
            extra_labels=["Claim"],
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
        """Store a reflection (Memory{memory_type:"reflection"}).

        Supports hierarchical reflection: if targets include reflection nodes,
        the new observation's reflection_depth is max(target_depths) + 1.
        All reflections have decay_class=permanent (they don't decay).
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

        # Reflections don't decay (per spec)
        props["memory_type"] = "reflection"
        props["decay_class"] = "permanent"
        props["layer"] = "meta"

        node = await self.store(
            scope=scope,
            content=observation,
            node_type="Memory",
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
        """Get reflections (Memory{memory_type:"reflection"}) about a node.

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

        sparse_indices: list[int] | None = None
        sparse_values: list[float] | None = None
        effective_mode = search_mode

        # Run dense embedding and sparse encoding in parallel when both are needed
        if search_mode in ("hybrid", "sparse") and self._sparse is not None:
            embed_task = self._embedding.embed_query(query)
            sparse_task = self._sparse.encode_query(query)
            try:
                query_vector, sparse = await asyncio.gather(embed_task, sparse_task)
                sparse_indices, sparse_values = self._sparse.to_qdrant(sparse)
            except Exception as exc:
                logger.warning(
                    "parallel_encode_failed",
                    error=str(exc),
                    fallback="dense",
                )
                # Fallback: try dense-only
                query_vector = await self._embedding.embed_query(query)
                effective_mode = "dense"
        else:
            query_vector = await self._embedding.embed_query(query)
            if search_mode in ("hybrid", "sparse") and self._sparse is None:
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

            node_confidence = effective_confidence(props)
            if min_confidence is not None and node_confidence < min_confidence:
                continue

            node_tags: list[str] = props.get("tags", [])
            if tags_filter and not any(t in node_tags for t in tags_filter):
                continue

            if not include_superseded and props.get("superseded_by"):
                continue

            # Filter superseded nodes: valid_to in the past means node was superseded
            if not include_superseded:
                valid_to = props.get("valid_to")
                if valid_to is not None:
                    vt = (
                        valid_to
                        if isinstance(valid_to, datetime)
                        else datetime.fromisoformat(str(valid_to))
                    )
                    if vt <= now:
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
                raw_heat = (
                    props["effective_heat"]
                    if "effective_heat" in props
                    else props.get("heat_score")
                )
                heat = float(raw_heat) if raw_heat is not None else 0.5
                relevance = relevance * ((1.0 - settings.heat_weight) + settings.heat_weight * heat)

            raw_credibility_factors = props.get("credibility_factors")
            credibility_factors: dict[str, Any] | None = None
            if isinstance(raw_credibility_factors, dict):
                credibility_factors = raw_credibility_factors

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
                    conflict_status=str(props.get("conflict_status") or "none"),
                    credibility=float(props.get("credibility") or 0.0),
                    credibility_factors=credibility_factors,
                    tier=props.get("tier"),
                    superseded_by=(
                        str(props["superseded_by"]) if props.get("superseded_by") else None
                    ),
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

        if rel_type == "SUPERSEDES":
            now = datetime.now(UTC).isoformat()
            await self._memgraph.execute_write(
                """
                MATCH (n {id: $to_id, silo_id: $silo_id})
                SET n.valid_to = $valid_to, n.superseded_by = $superseded_by
                """,
                {"to_id": to_node, "silo_id": silo_id, "valid_to": now, "superseded_by": from_node},
            )
            logger.info(
                "node_superseded",
                old_node=to_node,
                new_node=from_node,
                valid_to=now,
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
            layer_filter = f"AND neighbor.layer IN [{quoted}]"

        if not isinstance(max_depth, int):
            raise TypeError(f"max_depth must be an int, got {type(max_depth).__name__!r}")

        rows = await self._memgraph.execute_query(
            f"""
            UNWIND $start_ids AS seed_id
            MATCH (seed:Node {{id: seed_id, silo_id: $silo_id}})
            OPTIONAL MATCH path = (seed)-[*1..{max_depth}]-(neighbor:Node)
            WHERE neighbor.silo_id = $silo_id {layer_filter}
            WITH seed, [x IN COLLECT(DISTINCT neighbor) WHERE x IS NOT NULL] AS neighbors
            WITH [seed] + neighbors AS all_nodes
            UNWIND all_nodes AS n
            RETURN DISTINCT
                n.id AS node_id,
                n.type AS type,
                n.content AS content,
                COALESCE(n.layer, 'memory') AS layer,
                n.confidence AS confidence,
                n.status AS status
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
                    MATCH (a:Node {{id: nid}})-[r]->(b:Node)
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
                **({"status": r["status"]} if r.get("status") is not None else {}),
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
