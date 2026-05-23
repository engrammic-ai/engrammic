"""Memgraph implementation of HyperGraphStore."""

from __future__ import annotations

import time
import uuid
import uuid as uuid_mod
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from primitives.eag import EAGKnowledgeStore
from primitives.protocols import DeleteResult, IngestResult, KnowledgeNode, Scope

from context_service.config.logging import get_logger
from context_service.db import queries as db_queries
from context_service.db.schema import (
    LABEL_CLAIM,
    LABEL_DOCUMENT,
    LABEL_ENTITY,
    LABEL_PASSAGE,
    content_union_predicate,
)
from context_service.engine import queries
from context_service.engine.exceptions import ConflictError, StaleVersionError
from context_service.engine.models import BinaryEdge, HyperEdge, Node, Participant, Silo, SubGraph
from context_service.services.models import ScopeContext  # noqa: TC001
from context_service.telemetry.metrics import record_db_query
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from context_service.stores.memgraph import MemgraphClient

logger = get_logger(__name__)

# Labels that represent addressable content nodes in the graph.
_CONTENT_LABEL_SET: frozenset[str] = frozenset(
    {LABEL_DOCUMENT, LABEL_PASSAGE, LABEL_CLAIM, LABEL_ENTITY}
)
_PATH_LABEL_SET: frozenset[str] = _CONTENT_LABEL_SET

_SUPERSESSION_LOCK_PREFIX = "lock:supersession:"
_SUPERSESSION_LOCK_TTL_SECONDS = 30


def _node_to_knowledge_node(node: Node) -> KnowledgeNode:
    """Translate a context-service Node to the primitives KnowledgeNode protocol shape."""
    from primitives.protocols import Layer

    _layer_map = {
        "document": Layer.MEMORY,
        "passage": Layer.MEMORY,
        "claim": Layer.KNOWLEDGE,
        "entity": Layer.KNOWLEDGE,
    }
    layer = _layer_map.get(node.type or node.label or "", Layer.MEMORY)
    return KnowledgeNode(
        id=str(node.id),
        layer=layer,
        silo_id=str(node.silo_id),
        content=node.content,
        metadata=node.properties or {},
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _parse_dt(value: Any) -> datetime:
    """Parse a datetime from Memgraph -- handles str, native datetime, neo4j DateTime, and epoch-ms int."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Memgraph timestamp() returns epoch-microseconds (not ms)
        return datetime.fromtimestamp(value / 1_000_000.0, tz=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    # neo4j driver returns neo4j.time.DateTime -- convert via iso_format()
    if hasattr(value, "iso_format"):
        return datetime.fromisoformat(value.iso_format())
    if hasattr(value, "to_native"):
        native = value.to_native()
        if not isinstance(native, datetime):
            raise TypeError(f"to_native() returned {type(native).__name__!r}, expected datetime")
        return native
    return datetime.fromisoformat(str(value))


class MemgraphStore(EAGKnowledgeStore):
    """HyperGraphStore implementation backed by Memgraph.

    Inherits EAGKnowledgeStore to satisfy the primitives protocol contract.
    The five EAGKnowledgeStore abstract methods (ingest, query, get, get_batch,
    delete) operate on primitives' Scope/KnowledgeNode/IngestResult/DeleteResult
    types, while MemgraphStore's native API operates on context-service's own
    Node/ScopeContext domain models. The adapter stubs below mark the gap —
    they must be wired to the higher-level service layer (context_store /
    retrieval pipeline) before the EAG protocol can be used end-to-end.
    """

    def __init__(
        self,
        client: MemgraphClient,
        redis_client: Redis[bytes] | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._client = client
        self._redis = redis_client

    # --- EAGKnowledgeStore protocol adapters (not yet wired) ---

    async def ingest(
        self,
        content: str,
        metadata: dict[str, Any],
        scope: Scope,
    ) -> IngestResult:
        # Ingestion in context-service flows through the store-batch pipeline
        # (MCP context_store -> ingest service -> outbox -> Dagster assets).
        # This adapter cannot be wired at the MemgraphStore layer without
        # pulling in the full ingest service stack.
        raise NotImplementedError(
            "MemgraphStore.ingest: wire through context_service.services.ingest"
        )

    async def query(
        self,
        q: str,
        scope: Scope,
        limit: int = 10,
    ) -> list[KnowledgeNode]:
        # Retrieval in context-service uses the hybrid SPLADE+dense RRF pipeline
        # in context_service.retrieval, not a direct store method.
        raise NotImplementedError(
            "MemgraphStore.query: wire through context_service.retrieval pipeline"
        )

    async def get(self, node_id: str, scope: Scope) -> KnowledgeNode | None:
        # Adapter over get_node; translates primitives Scope -> silo_id string.
        node = await self.get_node(uuid.UUID(node_id), scope.silo_id)
        if node is None:
            return None
        return _node_to_knowledge_node(node)

    async def get_batch(self, node_ids: list[str], scope: Scope) -> list[KnowledgeNode]:
        # Adapter over batch_get_nodes.
        uuids = [uuid.UUID(nid) for nid in node_ids]
        node_map = await self.batch_get_nodes(uuids, scope.silo_id)
        return [_node_to_knowledge_node(n) for n in node_map.values()]

    async def delete(
        self,
        node_id: str,
        scope: Scope,
        cascade: bool = False,
    ) -> DeleteResult:
        # Cascade walk (DERIVED_FROM / CITES DAG) is not yet implemented;
        # see context/plans/cag-integration-audit.md right-to-erasure item.
        if cascade:
            raise NotImplementedError(
                "MemgraphStore.delete cascade=True: implement erasure DAG walk first"
            )
        deleted = await self.delete_node(uuid.UUID(node_id), scope.silo_id)
        return DeleteResult(deleted=deleted, node_id=node_id, cascade_count=0)

    # --- Helpers ---

    @staticmethod
    def _node_from_record(record: dict[str, Any]) -> Node:
        n = record["n"]
        props = n.get("properties", "{}")
        if isinstance(props, str):
            props = loads(props)
        supersedes_raw = n.get("supersedes_id")
        # Prefer record-level _labels (set by queries that do `labels(n) AS _labels`);
        # neo4j's result.data() flattens Node values to property dicts, so labels
        # are not available as a nested key on `n`. Fall back to nested keys for
        # tests that fabricate the shape directly.
        raw_labels: list[str] = (
            record.get("_labels")
            or record.get("labels")
            or n.get("_labels")
            or n.get("labels")
            or []
        )
        label = next(
            (lbl.lower() for lbl in raw_labels if lbl in _CONTENT_LABEL_SET),
            None,
        )

        # Phase-4 Document/Passage nodes are written with a different row
        # shape than the legacy flat Node schema: they lack `type`,
        # `content`, `version`, `valid_from`. Coerce on the way out so
        # downstream retrieval + graph walker + admin routes see a
        # uniform Node model. See context/plans/fix-retrieval-hydration-debt.md.
        if label == "document":
            node_type = "document"
            content = n.get("content") or n.get("raw_payload")
            version = int(n.get("current_version") or n.get("version") or 1)
            # Documents are written via UPSERT_DOCUMENT_AND_PASSAGES with
            # `d += $doc_props`, i.e. flat top-level keys — NOT a JSON-
            # encoded `properties` string like legacy :Node. Surface the
            # non-system keys as a `properties` dict so callers (REST
            # /context/{id}, bench corpus_doc_id round-trip) get them.
            _system_doc_keys = {
                "id",
                "silo_id",
                "committed",
                "current_version",
                "version",
                "created_at",
                "updated_at",
                "valid_from",
                "valid_to",
                "supersedes_id",
                "content",
                "type",
                "_labels",
                "labels",
                "uri",
                "mime",
                "source_type",
                "content_hash",
                "content_class",
                "ingest_class",
                "last_reset_at",
                "raw_payload",
                "raw_payload_truncated",
                "properties",
            }
            props = {k: v for k, v in n.items() if k not in _system_doc_keys}
        elif label == "passage":
            node_type = "passage"
            content = n.get("content") or n.get("text")
            version = int(n.get("current_version") or n.get("version") or 1)
        else:
            # Legacy :Node rows (and tests that fabricate them) plus
            # :Claim / :Entity which still use the flat shape.
            node_type = n["type"]
            content = n.get("content")
            version = int(n.get("version", 1))

        return Node(
            id=uuid.UUID(n["id"]),
            type=node_type,
            content=content,
            properties=props,
            silo_id=uuid.UUID(n["silo_id"]),
            source_uri=n.get("source_uri") or n.get("uri"),
            content_hash=n.get("content_hash"),
            stale=n.get("stale", False),
            version=version,
            created_at=_parse_dt(n["created_at"]),
            updated_at=_parse_dt(n["updated_at"]),
            last_accessed_at=_parse_dt(n["last_accessed_at"])
            if n.get("last_accessed_at")
            else None,
            valid_from=_parse_dt(n["valid_from"]) if n.get("valid_from") else datetime.now(UTC),
            valid_to=_parse_dt(n["valid_to"]) if n.get("valid_to") else None,
            supersedes_id=uuid.UUID(supersedes_raw) if supersedes_raw else None,
            label=label,
            ingest_class=n.get("ingest_class") or "standard",
            content_class=n.get("content_class") or "default",
            last_reset_at=_parse_dt(n["last_reset_at"]) if n.get("last_reset_at") else None,
            reclassified_at=_parse_dt(n["reclassified_at"]) if n.get("reclassified_at") else None,
        )

    @staticmethod
    def _silo_from_record(record: dict[str, Any]) -> Silo:
        s = record["s"]
        meta = s.get("metadata", "{}")
        if isinstance(meta, str):
            meta = loads(meta)
        return Silo(
            id=uuid.UUID(s["id"]),
            name=s["name"],
            description=s.get("description"),
            org_id=s["org_id"],
            dissolvability=s.get("dissolvability", 0.5),
            metadata=meta,
            created_at=_parse_dt(s["created_at"]),
            updated_at=_parse_dt(s["updated_at"]),
        )

    @staticmethod
    def _binary_edge_from_record(record: dict[str, Any]) -> BinaryEdge:
        e = record["e"]
        props = e.get("properties", "{}")
        if isinstance(props, str):
            props = loads(props)
        # source_id and target_id come from the matched nodes
        return BinaryEdge(
            id=uuid.UUID(e["id"]),
            type=e["type"],
            source_id=uuid.UUID(e.get("source_id", e["id"])),
            target_id=uuid.UUID(record.get("b", {}).get("id", e["id"])),
            properties=props,
            created_at=_parse_dt(e["created_at"]),
        )

    @staticmethod
    def _hyperedge_from_record(record: dict[str, Any]) -> HyperEdge:
        he = record["he"]
        props = he.get("properties", "{}")
        if isinstance(props, str):
            props = loads(props)
        participants_raw = record.get("participants", [])
        participants = [
            Participant(node_id=uuid.UUID(p["node_id"]), role=p["role"])
            for p in participants_raw
            if p.get("node_id") is not None
        ]
        return HyperEdge(
            id=uuid.UUID(he["id"]),
            type=he["type"],
            participants=participants if len(participants) >= 3 else [],
            properties=props,
            created_at=_parse_dt(he["created_at"]),
        )

    # --- Node CRUD ---

    @staticmethod
    def _node_upsert_row(node: Node) -> dict[str, Any]:
        valid_from = (
            node.valid_from.isoformat() if node.valid_from else datetime.now(UTC).isoformat()
        )
        return {
            "id": str(node.id),
            "type": node.type,
            "content": node.content,
            "properties": dumps(node.properties),
            "silo_id": str(node.silo_id),
            "source_uri": node.source_uri,
            "content_hash": node.content_hash,
            "stale": node.stale,
            "extraction_status": node.extraction_status,
            "expected_version": node.version,
            "valid_from": valid_from,
            "new_id": str(uuid_mod.uuid4()),
            "ingest_class": node.ingest_class,
            "content_class": node.content_class,
        }

    async def upsert_node(self, node: Node) -> None:
        start = time.perf_counter()
        try:
            params = self._node_upsert_row(node)
            result = await self._client.execute_write(queries.UPSERT_NODE_SINGLE_RTT, params)
            if not result:
                return
            action = result[0].get("action")
            if action == "stale":
                stored_version = result[0].get("stored_version") or 0
                raise StaleVersionError(str(node.id), node.version, int(stored_version))
        finally:
            record_db_query("memgraph.upsert_node", (time.perf_counter() - start) * 1000)

    async def update_extraction_status(self, node_id: str, silo_id: str, status: str) -> None:
        """Update the extraction_status field on a node."""
        await self._client.execute_write(
            queries.UPDATE_EXTRACTION_STATUS,
            {"id": node_id, "silo_id": silo_id, "extraction_status": status},
        )

    async def silo_extraction_status(self, silo_id: str) -> dict[str, int]:
        """Return {status: count} for all nodes in a silo."""
        rows = await self._client.execute_query(
            queries.SILO_EXTRACTION_STATUS,
            {"silo_id": silo_id},
        )
        return {r["status"] or "none": r["count"] for r in rows}

    async def get_node(self, node_id: uuid.UUID, silo_id: str) -> Node | None:
        result = await self._client.execute_query(
            queries.GET_NODE_RETRIEVAL,
            {"id": str(node_id), "silo_id": silo_id},
        )
        if not result:
            return None
        return self._node_from_record(result[0])

    async def get_node_as_of(
        self, node_id: uuid.UUID, silo_id: str, as_of: datetime
    ) -> Node | None:
        start = time.perf_counter()
        try:
            as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
            records = await self._client.execute_query(
                queries.GET_NODE_AS_OF,
                {
                    "id": str(node_id),
                    "silo_id": silo_id,
                    "as_of": int(as_of_utc.timestamp() * 1_000_000),
                },
            )
            if not records:
                return None
            return self._node_from_record(records[0])
        finally:
            record_db_query("memgraph.temporal_query", (time.perf_counter() - start) * 1000)

    async def filter_superseded_at(
        self,
        node_ids: list[uuid.UUID],
        silo_id: str,
        as_of: datetime,
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Map each input id to the node that represents its valid version at ``as_of``.

        An input id maps to:
        - itself if it was valid at ``as_of`` (valid_from <= as_of < valid_to OR valid_to IS NULL)
        - a different id if it was superseded and the SUPERSEDES chain
          has a tip that is valid at ``as_of``
        - absent from the result if no valid version exists at ``as_of``

        Caller is responsible for substituting ids in the result set.
        """
        if not node_ids:
            return {}
        # Documents written via UPSERT_DOCUMENT_AND_PASSAGES store
        # created_at via Cypher `timestamp()` which returns epoch
        # microseconds as an integer; their valid_from is absent. We
        # coalesce to created_at in the query, so $as_of must be the
        # same numeric shape — otherwise string/int compare yields
        # null and every candidate is filtered out.
        as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        records = await self._client.execute_query(
            queries.FILTER_SUPERSEDED_AT,
            {
                "ids": [str(nid) for nid in node_ids],
                "silo_id": silo_id,
                "as_of": int(as_of_utc.timestamp() * 1_000_000),
            },
        )
        result: dict[uuid.UUID, uuid.UUID] = {}
        for rec in records:
            input_id = uuid.UUID(rec["input_id"])
            valid_id = uuid.UUID(rec["valid_id"]) if rec.get("valid_id") else None
            if valid_id is not None:
                result[input_id] = valid_id
        return result

    async def _acquire_supersession_lock(self, predecessor_id: str) -> bool:
        """Acquire a Redis lock before superseding a node.

        Returns True if the lock was acquired, False if another writer holds it.
        The lock expires automatically after _SUPERSESSION_LOCK_TTL_SECONDS to
        prevent deadlocks from crashed callers.

        If no Redis client is configured, returns True (graceful degradation).
        """
        if self._redis is None:
            return True
        lock_key = f"{_SUPERSESSION_LOCK_PREFIX}{predecessor_id}"
        try:
            result = await self._redis.set(
                lock_key, "1", nx=True, ex=_SUPERSESSION_LOCK_TTL_SECONDS
            )
            return bool(result)
        except Exception:
            logger.error(
                "supersession_lock_acquire_error",
                predecessor_id=predecessor_id,
                exc_info=True,
            )
            # Fail open: allow the write rather than blocking all supersessions
            # when Redis is unavailable.
            return True

    async def _release_supersession_lock(self, predecessor_id: str) -> None:
        """Release the supersession lock for the given predecessor node."""
        if self._redis is None:
            return
        lock_key = f"{_SUPERSESSION_LOCK_PREFIX}{predecessor_id}"
        try:
            await self._redis.delete(lock_key)
        except Exception:
            logger.error(
                "supersession_lock_release_error",
                predecessor_id=predecessor_id,
                exc_info=True,
            )

    async def create_supersedes_edge(
        self,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
        silo_id: str,
        valid_from: datetime,
        source: str = "custodian",
        reason: str = "contradiction",
    ) -> bool:
        """Create a cross-node SUPERSEDES edge.

        Links an existing ``from_id`` (the newer, superseding node) to an
        existing ``to_id`` (the older, superseded node). Sets ``old.valid_to``
        to ``valid_from`` if not already set. Used by the Custodian semantic
        supersession pass. ``source`` tags the edge's origin mechanism so
        downstream attribution can distinguish per-cluster from cross-cluster
        detections. ``reason`` must be one of: contradiction, evidence_shift,
        author_update, evidence_erased (I5).

        Acquires a Redis lock on ``to_id`` before writing to prevent a race
        condition where two concurrent transactions both read the same tail_id
        and overwrite each other's head_id pointer (last-write-wins orphan).
        Raises ConflictError if the lock cannot be acquired.
        """
        predecessor_id = str(to_id)
        if not await self._acquire_supersession_lock(predecessor_id):
            logger.warning("supersession_lock_contention", predecessor_id=predecessor_id)
            raise ConflictError(f"Concurrent supersession of {predecessor_id}")
        try:
            result = await self._client.execute_write(
                queries.CREATE_CROSS_NODE_SUPERSEDES,
                {
                    "from_id": str(from_id),
                    "to_id": str(to_id),
                    "silo_id": silo_id,
                    "valid_from": valid_from.isoformat(),
                    "source": source,
                    "reason": reason,
                },
            )
            return bool(result and result[0].get("created", 0) > 0)
        finally:
            await self._release_supersession_lock(predecessor_id)

    async def resolve_current_head(
        self,
        node_id: uuid.UUID,
        silo_id: str,
    ) -> uuid.UUID | None:
        """Resolve the current chain head for a node using O(1) pointer lookup.

        Returns the head node's id, or the input id if it's standalone/head.
        Returns None if node doesn't exist.
        """
        result = await self._client.execute_query(
            queries.RESOLVE_CURRENT_HEAD,
            {"id": str(node_id), "silo_id": silo_id},
        )
        if not result:
            return None
        head_id = result[0].get("head_id")
        return uuid.UUID(head_id) if head_id else None

    async def batch_get_nodes(
        self, node_ids: list[uuid.UUID], silo_id: str
    ) -> dict[uuid.UUID, Node]:
        if not node_ids:
            return {}
        result = await self._client.execute_query(
            queries.BATCH_GET_NODES,
            {"ids": [str(nid) for nid in node_ids], "silo_id": silo_id},
        )
        return {uuid.UUID(r["n"]["id"]): self._node_from_record(r) for r in result}

    async def delete_node(self, node_id: uuid.UUID, silo_id: str) -> bool:
        start = time.perf_counter()
        try:
            result = await self._client.execute_write(
                queries.DELETE_NODE,
                {"id": str(node_id), "silo_id": silo_id},
            )
            return bool(result and result[0].get("deleted", 0) > 0)
        finally:
            record_db_query("memgraph.delete_node", (time.perf_counter() - start) * 1000)

    async def find_nodes(
        self,
        silo_id: str,
        *,
        type: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[Node], str | None]:
        offset = int(cursor) if cursor else 0
        result = await self._client.execute_query(
            queries.FIND_NODES,
            {
                "silo_id": silo_id,
                "type": type,
                "offset": offset,
                "limit": limit + 1,
            },
        )
        nodes = [self._node_from_record(r) for r in result[:limit]]
        next_cursor = str(offset + limit) if len(result) > limit else None
        return nodes, next_cursor

    async def count_nodes(self, silo_id: str) -> int:
        result = await self._client.execute_query(
            queries.COUNT_NODES,
            {"silo_id": silo_id},
        )
        count: int = result[0]["count"] if result else 0
        return count

    async def count_edges_in_silo(self, silo_id: str) -> int:
        result = await self._client.execute_query(
            queries.COUNT_EDGES_IN_SILO,
            {"silo_id": silo_id},
        )
        count: int = result[0]["count"] if result else 0
        return count

    async def sum_content_bytes_in_silo(self, silo_id: str) -> int:
        result = await self._client.execute_query(
            queries.SUM_CONTENT_BYTES_IN_SILO,
            {"silo_id": silo_id},
        )
        if not result:
            return 0
        value = result[0].get("bytes")
        return int(value) if value is not None else 0

    async def find_node_by_source_uri(self, silo_id: uuid.UUID, source_uri: str) -> Node | None:
        result = await self._client.execute_query(
            queries.FIND_NODE_BY_SOURCE_URI,
            {"silo_id": str(silo_id), "source_uri": source_uri},
        )
        if not result:
            return None
        return self._node_from_record(result[0])

    async def list_nodes_with_uri(self, silo_id: uuid.UUID) -> list[dict[str, Any]]:
        return await self._client.execute_query(
            queries.LIST_NODES_WITH_URI_BY_SILO,
            {"silo_id": str(silo_id)},
        )

    async def mark_node_stale(self, node_id: uuid.UUID, silo_id: str, version: int) -> bool:
        result = await self._client.execute_query(
            queries.MARK_NODE_STALE,
            {"id": str(node_id), "silo_id": silo_id, "expected_version": version},
        )
        return len(result) > 0

    # --- Binary Edge CRUD ---

    async def upsert_binary_edge(self, edge: BinaryEdge, silo_id: str) -> None:
        start = time.perf_counter()
        try:
            await self._client.execute_write(
                queries.CREATE_BINARY_EDGE,
                {
                    "id": str(edge.id),
                    "type": edge.type,
                    "source_id": str(edge.source_id),
                    "target_id": str(edge.target_id),
                    "properties": dumps(edge.properties),
                    "silo_id": silo_id,
                },
            )
        finally:
            record_db_query("memgraph.create_edge", (time.perf_counter() - start) * 1000)

    async def get_binary_edges(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        type: str | None = None,
        direction: Literal["outgoing", "incoming", "both"] = "both",
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[BinaryEdge], str | None]:
        offset = int(cursor) if cursor else 0
        query_map = {
            "outgoing": queries.GET_BINARY_EDGES_OUTGOING,
            "incoming": queries.GET_BINARY_EDGES_INCOMING,
            "both": queries.GET_BINARY_EDGES_BOTH,
        }
        result = await self._client.execute_query(
            query_map[direction],
            {
                "node_id": str(node_id),
                "silo_id": silo_id,
                "type": type,
                "offset": offset,
                "limit": limit + 1,
            },
        )
        edges = [self._binary_edge_from_record(r) for r in result[:limit]]
        next_cursor = str(offset + limit) if len(result) > limit else None
        return edges, next_cursor

    async def get_entity_graph_neighbors(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        limit: int = 50,
    ) -> list[tuple[Node, int]]:
        """Find neighbor Nodes reachable via the entity-graph projection.

        Returns list of (neighbor_node, strength) tuples where strength is
        the count of distinct semantic relationships bridging the two source
        nodes through their extracted entities. Higher strength = more
        conceptually connected. Used by GraphWalker when traversing the
        knowledge graph produced by LLM extraction.
        """
        result = await self._client.execute_query(
            queries.GET_ENTITY_GRAPH_NEIGHBORS,
            {
                "node_id": str(node_id),
                "silo_id": silo_id,
                "limit": limit,
            },
        )
        neighbors: list[tuple[Node, int]] = []
        for row in result:
            # The Cypher query returns rows with keys {b, shared_links,
            # bridge_entities}. The _node_from_record helper expects a
            # dict where the node is under key "n", so wrap accordingly.
            node = self._node_from_record({"n": row["b"]})
            strength = int(row["shared_links"])
            neighbors.append((node, strength))
        return neighbors

    async def delete_binary_edge(self, edge_id: uuid.UUID, silo_id: str) -> bool:
        start = time.perf_counter()
        try:
            result = await self._client.execute_write(
                queries.DELETE_BINARY_EDGE,
                {"id": str(edge_id), "silo_id": silo_id},
            )
            return bool(result and result[0].get("deleted", 0) > 0)
        finally:
            record_db_query("memgraph.delete_edge", (time.perf_counter() - start) * 1000)

    # --- HyperEdge CRUD ---

    async def upsert_hyperedge(self, edge: HyperEdge, silo_id: str) -> None:
        await self._client.execute_write(
            queries.UPSERT_HYPEREDGE_WITH_PARTICIPANTS,
            {
                "id": str(edge.id),
                "type": edge.type,
                "properties": dumps(edge.properties),
                "silo_id": silo_id,
                "participants": [
                    {"node_id": str(p.node_id), "role": p.role} for p in edge.participants
                ],
            },
        )

    async def get_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> HyperEdge | None:
        result = await self._client.execute_query(
            queries.GET_HYPEREDGE,
            {"id": str(edge_id), "silo_id": silo_id},
        )
        if not result:
            return None
        return self._hyperedge_from_record(result[0])

    async def get_hyperedges_for_node(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        type: str | None = None,
        role: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[HyperEdge], str | None]:
        offset = int(cursor) if cursor else 0
        result = await self._client.execute_query(
            queries.GET_HYPEREDGES_FOR_NODE,
            {
                "node_id": str(node_id),
                "silo_id": silo_id,
                "type": type,
                "role": role,
                "offset": offset,
                "limit": limit + 1,
            },
        )
        edges = [self._hyperedge_from_record(r) for r in result[:limit]]
        next_cursor = str(offset + limit) if len(result) > limit else None
        return edges, next_cursor

    async def delete_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> bool:
        result = await self._client.execute_write(
            queries.DELETE_HYPEREDGE,
            {"id": str(edge_id), "silo_id": silo_id},
        )
        return bool(result and result[0].get("deleted", 0) > 0)

    # --- Silo CRUD ---

    async def create_silo(self, silo: Silo) -> None:
        await self._client.execute_write(
            queries.CREATE_SILO,
            {
                "id": str(silo.id),
                "name": silo.name,
                "description": silo.description,
                "org_id": silo.org_id,
                "dissolvability": silo.dissolvability,
                "metadata": dumps(silo.metadata),
            },
        )

    async def get_silo(self, scope: ScopeContext) -> Silo | None:
        result = await self._client.execute_query(
            queries.GET_SILO,
            {"id": str(scope.silo_id), "org_id": scope.org_id},
        )
        if not result:
            return None
        return self._silo_from_record(result[0])

    async def list_silos(self, org_id: str) -> list[Silo]:
        result = await self._client.execute_query(
            queries.LIST_SILOS,
            {"org_id": org_id},
        )
        return [self._silo_from_record(r) for r in result]

    async def update_silo(self, silo: Silo) -> None:
        await self._client.execute_write(
            queries.UPDATE_SILO,
            {
                "id": str(silo.id),
                "org_id": silo.org_id,
                "name": silo.name,
                "description": silo.description,
                "dissolvability": silo.dissolvability,
                "metadata": dumps(silo.metadata),
            },
        )

    async def delete_silo(self, scope: ScopeContext) -> bool:
        result = await self._client.execute_write(
            queries.DELETE_SILO,
            {"id": str(scope.silo_id), "org_id": scope.org_id},
        )
        return bool(result and result[0].get("deleted", 0) > 0)

    async def reset_silo(self, silo_id: uuid.UUID) -> int:
        """Delete all nodes and edges in a silo, preserving the silo record.

        Returns the count of deleted nodes.
        """
        result = await self._client.execute_write(
            queries.RESET_SILO,
            {"silo_id": str(silo_id)},
        )
        return result[0].get("deleted_nodes", 0) if result else 0

    # --- Graph Traversal ---

    async def neighborhood(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 100,
        silo_scope: list[str] | None = None,
    ) -> SubGraph:
        start = time.perf_counter()
        try:
            if not isinstance(max_depth, int):
                raise TypeError(f"max_depth must be int, got {type(max_depth).__name__}")
            if not isinstance(max_nodes, int):
                raise TypeError(f"max_nodes must be int, got {type(max_nodes).__name__}")
            capped_depth = min(max_depth, 5)  # hard cap
            capped_nodes = min(max_nodes, 500)  # hard cap
            query = queries.NEIGHBORHOOD % (capped_depth * 2)  # *2 for bipartite hops
            result = await self._client.execute_query(
                query,
                {
                    "id": str(node_id),
                    "silo_id": silo_id,
                    "max_nodes": capped_nodes,
                },
            )
            nodes: dict[uuid.UUID, Node] = {}
            for r in result:
                node = self._node_from_record({"n": r["other"]})
                if silo_scope is None or str(node.silo_id) in silo_scope:
                    nodes[node.id] = node

            # Fetch edges between the discovered nodes
            binary_edges: list[BinaryEdge] = []
            if nodes:
                node_ids = [str(nid) for nid in nodes]
                _a_pred = content_union_predicate("a")
                _b_pred = content_union_predicate("b")
                edge_result = await self._client.execute_query(
                    f"""
                    MATCH (a)-[e:EDGE]->(b)
                    WHERE {_a_pred} AND {_b_pred}
                      AND a.committed = true AND b.committed = true
                      AND a.id IN $ids AND b.id IN $ids AND a.silo_id = $silo_id
                    RETURN e.id AS id, e.type AS type, e.properties AS properties,
                           e.silo_id AS silo_id, e.created_at AS created_at,
                           a.id AS source_id, b.id AS target_id
    """,
                    {"ids": node_ids, "silo_id": silo_id},
                )
                for r in edge_result:
                    props = r.get("properties", "{}")
                    if isinstance(props, str):
                        props = loads(props)
                    binary_edges.append(
                        BinaryEdge(
                            id=uuid.UUID(r["id"]),
                            type=r["type"],
                            source_id=uuid.UUID(r["source_id"]),
                            target_id=uuid.UUID(r["target_id"]),
                            properties=props if isinstance(props, dict) else {},
                            created_at=_parse_dt(r["created_at"]),
                        )
                    )

            return SubGraph(nodes=nodes, binary_edges=binary_edges, root_id=node_id)
        finally:
            record_db_query("memgraph.get_neighbors", (time.perf_counter() - start) * 1000)

    async def shared_participation(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        threshold: int = 2,
        limit: int = 50,
    ) -> list[tuple[Node, int]]:
        result = await self._client.execute_query(
            queries.SHARED_PARTICIPATION,
            {
                "id": str(node_id),
                "silo_id": silo_id,
                "threshold": threshold,
                "limit": limit,
            },
        )
        return [(self._node_from_record({"n": r["b"]}), r["shared_count"]) for r in result]

    async def shortest_path(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 5,
    ) -> list[Node] | None:
        start = time.perf_counter()
        try:
            if not isinstance(max_depth, int):
                raise TypeError(f"max_depth must be int, got {type(max_depth).__name__}")
            capped_depth = min(max_depth, 5) * 2  # *2 for bipartite
            query = queries.SHORTEST_PATH % capped_depth
            result = await self._client.execute_query(
                query,
                {
                    "source_id": str(source_id),
                    "target_id": str(target_id),
                    "silo_id": silo_id,
                },
            )
            if not result:
                return None
            path_nodes = result[0].get("path_nodes", [])
            content_labels = _PATH_LABEL_SET
            out: list[Node] = []
            for n in path_nodes:
                labels = n.get("labels", n.get("_labels", []))
                if not content_labels.intersection(labels):
                    continue
                out.append(self._node_from_record({"n": n, "_labels": labels}))
            return out
        finally:
            record_db_query("memgraph.graph_search", (time.perf_counter() - start) * 1000)

    # --- Export (Visualization) ---

    async def export_nodes(self, silo_id: str, *, limit: int = 500, offset: int = 0) -> list[Node]:
        result = await self._client.execute_query(
            queries.EXPORT_ALL_NODES,
            {"silo_id": silo_id, "offset": offset, "limit": limit},
        )
        return [self._node_from_record(r) for r in result]

    async def export_binary_edges(
        self, silo_id: str, *, limit: int = 500, offset: int = 0
    ) -> list[BinaryEdge]:
        result = await self._client.execute_query(
            queries.EXPORT_ALL_BINARY_EDGES,
            {"silo_id": silo_id, "offset": offset, "limit": limit},
        )
        edges = []
        for r in result:
            props = r.get("properties", "{}")
            if isinstance(props, str):
                props = loads(props)
            edges.append(
                BinaryEdge(
                    id=uuid.UUID(r["id"]),
                    type=r["type"],
                    source_id=uuid.UUID(r["source_id"]),
                    target_id=uuid.UUID(r["target_id"]),
                    properties=props if isinstance(props, dict) else {},
                    created_at=_parse_dt(r["created_at"]),
                )
            )
        return edges

    async def export_hyperedges(
        self, silo_id: str, *, limit: int = 500, offset: int = 0
    ) -> list[HyperEdge]:
        result = await self._client.execute_query(
            queries.EXPORT_ALL_HYPEREDGES,
            {"silo_id": silo_id, "offset": offset, "limit": limit},
        )
        return [self._hyperedge_from_record(r) for r in result]

    # --- Agent Identity (v1.5 phase 5a) ---

    async def upsert_agent(
        self,
        agent_id: str,
        silo_id: str,
        *,
        role: str = "agent",
        parent_agent_id: str | None = None,
        lineage_root_id: str | None = None,
    ) -> str:
        """Create or return an :Agent node and optionally link it to a parent via SPAWNED_BY.

        Validates that parent_agent_id exists in the same silo before writing the
        SPAWNED_BY edge. Lineage depth is capped at 3 hops by the Cypher query.

        Returns the agent_id on success.
        Raises ValueError if parent_agent_id is provided but does not exist in silo.
        """
        now = datetime.now(UTC).isoformat()

        # Resolve lineage_root_id: if a parent is provided and no explicit root is
        # given, inherit the parent's lineage_root_id (falling back to parent itself).
        resolved_root = lineage_root_id

        if parent_agent_id is not None:
            parent_rows = await self._client.execute_query(
                db_queries.GET_AGENT_IN_SILO,
                {"agent_id": parent_agent_id, "silo_id": silo_id},
            )
            if not parent_rows:
                raise ValueError(
                    f"parent_agent_id {parent_agent_id!r} not found in silo {silo_id!r}"
                )
            if resolved_root is None:
                resolved_root = parent_rows[0].get("lineage_root_id") or parent_agent_id

        await self._client.execute_write(
            db_queries.UPSERT_AGENT,
            {
                "agent_id": agent_id,
                "silo_id": silo_id,
                "role": role,
                "lineage_root_id": resolved_root or agent_id,
                "created_at": now,
            },
        )

        if parent_agent_id is not None:
            await self._client.execute_write(
                db_queries.CREATE_SPAWNED_BY_EDGE,
                {
                    "child_agent_id": agent_id,
                    "parent_agent_id": parent_agent_id,
                    "silo_id": silo_id,
                    "created_at": now,
                },
            )

        return agent_id

    # --- ReasoningChain Projection (hybrid storage) ---

    async def upsert_reasoning_chain(
        self,
        chain_id: str,
        silo_id: str,
        step_count: int,
        first_step: str | None,
        final_step: str | None,
        outcome: str | None,
        all_premise_refs: list[str],
        produced_by_model: str,
        produced_by_agent_id: str,
        query_context_hash: str | None = None,
        status: str = "draft",
        source: str = "agent_explicit",
        conclusion: str | None = None,
    ) -> None:
        """Upsert a :ReasoningChain summary projection.

        Writes the summary fields needed for graph traversal and custodian
        scoring. Full steps are stored in Postgres by ChainSagaWriter before
        this method is called.
        """
        now = datetime.now(UTC).isoformat()
        await self._client.execute_write(
            """
            MERGE (n:ReasoningChain:Node {id: $chain_id, silo_id: $silo_id})
            ON CREATE SET
                n.step_count = $step_count,
                n.first_step = $first_step,
                n.final_step = $final_step,
                n.outcome = $outcome,
                n.conclusion = $conclusion,
                n.all_premise_refs = $all_premise_refs,
                n.produced_by_model = $produced_by_model,
                n.produced_by_agent_id = $produced_by_agent_id,
                n.query_context_hash = $query_context_hash,
                n.status = $status,
                n.source = $source,
                n.layer = "intelligence",
                n.type = "ReasoningChain",
                n.committed = true,
                n.created_at = $now
            ON MATCH SET
                n.step_count = $step_count,
                n.first_step = $first_step,
                n.final_step = $final_step,
                n.outcome = $outcome,
                n.conclusion = $conclusion,
                n.all_premise_refs = $all_premise_refs,
                n.status = $status,
                n.query_context_hash = $query_context_hash
            """,
            {
                "chain_id": chain_id,
                "silo_id": silo_id,
                "step_count": step_count,
                "first_step": first_step,
                "final_step": final_step,
                "outcome": outcome,
                "conclusion": conclusion,
                "all_premise_refs": all_premise_refs,
                "produced_by_model": produced_by_model,
                "produced_by_agent_id": produced_by_agent_id,
                "query_context_hash": query_context_hash,
                "status": status,
                "source": source,
                "now": now,
            },
        )

    # --- Bulk Operations ---

    async def batch_upsert_nodes(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        rows = [self._node_upsert_row(n) for n in nodes]
        result = await self._client.execute_write(queries.BATCH_UPSERT_NODES, {"rows": rows})
        for node, row in zip(nodes, result, strict=False):
            if row.get("action") == "stale":
                stored_version = row.get("stored_version") or 0
                raise StaleVersionError(str(node.id), node.version, int(stored_version))

    async def batch_upsert_binary_edges(self, edges: list[BinaryEdge], silo_id: str) -> None:
        if not edges:
            return
        rows = [
            {
                "id": str(edge.id),
                "type": edge.type,
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "properties": dumps(edge.properties),
                "silo_id": silo_id,
            }
            for edge in edges
        ]
        await self._client.execute_write(queries.BATCH_UPSERT_BINARY_EDGES, {"rows": rows})

    async def find_stale_chain_interior(
        self,
        silo_id: str,
        max_length: int,
        batch_size: int = 100,
    ) -> list[str]:
        """Find interior chain nodes beyond max_length hops from the chain head.

        Interior nodes are those with at least one predecessor (head side) and
        at least one successor (tail side) in a SUPERSEDES chain. Returns node
        ids for nodes that are not yet stubbed and sit more than max_length
        hops from the head, so the Custodian can prune them in batches.
        """
        result = await self._client.execute_query(
            queries.FIND_STALE_CHAIN_INTERIOR,
            {"silo_id": silo_id, "max_length": max_length, "batch_size": batch_size},
        )
        return [row["node_id"] for row in result]

    async def convert_to_stub(self, node_id: str, silo_id: str) -> bool:
        """Convert a node to a stub by clearing content fields while preserving edges.

        Sets ``stub=true`` and nulls out ``content``, ``content_hash``, and
        ``embedding`` so the storage footprint for deep chain interiors is
        bounded. The SUPERSEDES edges and all metadata (valid_from, heat_score,
        etc.) are left intact for provenance and time-travel queries.

        Returns True if the node was found and updated, False otherwise.
        """
        now_micros = int(datetime.now(UTC).timestamp() * 1_000_000)
        result = await self._client.execute_write(
            queries.CONVERT_TO_STUB,
            {"id": node_id, "silo_id": silo_id, "stubbed_at": now_micros},
        )
        return bool(result)

    async def batch_touch_accessed(self, node_ids: list[uuid.UUID], silo_id: str) -> int:
        """Update last_accessed_at for a batch of nodes."""
        if not node_ids:
            return 0
        result = await self._client.execute_write(
            queries.BATCH_TOUCH_NODES_ACCESSED,
            {"ids": [str(nid) for nid in node_ids], "silo_id": silo_id},
        )
        return result[0].get("touched", 0) if result else 0

    # --- Schema ---

    async def ensure_indexes(self) -> None:
        for query in queries.INDEX_QUERIES:
            try:
                await self._client.execute_query(query)
            except Exception:
                logger.debug(f"Index may already exist: {query[:60]}...")

    # --- Raw Cypher escape hatches ---

    async def execute_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Delegate a read-only Cypher query to the underlying MemgraphClient."""
        start = time.perf_counter()
        try:
            return await self._client.execute_query(cypher, params)
        finally:
            record_db_query("memgraph.query", (time.perf_counter() - start) * 1000)

    async def execute_write(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Delegate a write Cypher query to the underlying MemgraphClient."""
        return await self._client.execute_write(cypher, params)

    def session(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding a MemgraphClient session."""
        return self._client.session()

    def transaction(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding an explicit transaction."""
        return self._client.transaction()
