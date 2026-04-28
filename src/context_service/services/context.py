"""Context management service (thin slice)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog
from primitives.schema.labels import ALL_CITE_LABELS

from context_service.services.models import (
    GraphResult,
    LookupResult,
    Node,
    QueryResult,
    ScopeContext,
    ScoredNode,
    derive_silo_id,
)

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.services.context_meta import (
        HistoryResult,
        ProvenanceResult,
        ReasoningChainResult,
    )
    from context_service.stores import MemgraphClient, QdrantClient, RedisClient

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
            node_type: Node type label — must be in _ALLOWED_NODE_TYPES.
            properties: Optional metadata persisted to Memgraph via SET n += $props.
            idempotency_key: For deduplication.
            source_uri: Origin URI.

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
                created_at: timestamp()
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
        }
        if extra_props:
            params["extra_props"] = extra_props

        await self._memgraph.execute_write(create_query, params)

        if content and len(content) >= MIN_CONTENT_FOR_EMBEDDING and self._embedding:
            # Qdrant failure is not swallowed: a node in Memgraph without a
            # vector is invisible to semantic search (silent desync). Failing
            # here lets the caller retry the whole operation atomically.
            # Tradeoff: callers that tolerate graph-only storage must catch and
            # handle this explicitly; the alternative (marking _qdrant_sync_pending
            # on the node) would require a separate reconciliation worker.
            vector = await self._embedding.embed_single(content)
            await self._qdrant.upsert(
                node_id=str(node.id),
                vector=vector,
                payload={"type": node_type},
                silo_id=str(silo_id),
            )

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
                        data = json.loads(raw)
                        result[nid] = Node(
                            id=uuid.UUID(data["id"]),
                            type=data["type"],
                            content=data["content"],
                            properties=data.get("properties", {}),
                            silo_id=uuid.UUID(data["silo_id"]) if data.get("silo_id") else None,
                            source_uri=data.get("source_uri"),
                            content_hash=data.get("content_hash"),
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
                       n.content_hash AS content_hash
                """,
                {"ids": miss_ids, "silo_id": str(silo_id)},
            )
            for row in db_rows:
                node = Node(
                    id=uuid.UUID(row["id"]),
                    type=row["type"],
                    content=row["content"],
                    silo_id=uuid.UUID(row["silo_id"]) if row.get("silo_id") else None,
                    source_uri=row.get("source_uri"),
                    content_hash=row.get("content_hash"),
                )
                result[row["id"]] = node
                if self._cache:
                    cache_key = f"node:{silo_id}:{row['id']}"
                    cache_data = {
                        "id": str(node.id),
                        "type": node.type,
                        "content": node.content,
                        "silo_id": str(node.silo_id) if node.silo_id else None,
                        "source_uri": node.source_uri,
                        "content_hash": node.content_hash,
                    }
                    await self._cache.set(cache_key, json.dumps(cache_data).encode())

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

        chain_rows = await self._memgraph.execute_query(
            q.PROVENANCE_CHAIN,
            {"node_id": node_id, "silo_id": silo_id},
        )
        root_rows = await self._memgraph.execute_query(
            q.PROVENANCE_ROOT_SOURCES,
            {"node_id": node_id, "silo_id": silo_id},
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
            rows = await self._memgraph.execute_query(
                q.BELIEF_HISTORY_BY_NODE,
                {"node_id": node_id, "silo_id": silo_id},
            )
            current_rows = await self._memgraph.execute_query(
                q.BELIEF_HISTORY_CURRENT,
                {"node_id": node_id, "silo_id": silo_id},
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
            "steps": json.dumps(steps_data),
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
                "steps": json.dumps(steps_data),
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
    ) -> Node:
        """Assert a claim to Knowledge layer with evidence."""
        from context_service.models.mcp import SPOClaim

        props = dict(metadata or {})
        props["layer"] = "knowledge"
        props["source_type"] = source_type.value if hasattr(source_type, "value") else source_type
        props["confidence"] = confidence
        props["evidence"] = evidence
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

        for ev_ref in evidence:
            if ev_ref.startswith("node:"):
                ev_node_id = ev_ref[5:]
                await self._memgraph.execute_write(
                    """
                    MATCH (claim {id: $claim_id}), (ev {id: $ev_id})
                    MERGE (claim)-[:DERIVED_FROM]->(ev)
                    """,
                    {"claim_id": str(node.id), "ev_id": ev_node_id},
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
        """Promote a :Claim to :Claim:Fact when the epistemology agrees.

        Returns the updated node properties dict on promotion, or None if the
        promotion was skipped (decision said no, or claim was already a :Fact).
        Best-effort — DB errors are logged and re-raised for the caller to
        decide.
        """
        from context_service.custodian.fact_promotion import evaluate_claim_for_fact
        from context_service.db.queries import PROMOTE_CLAIM_TO_FACT

        if evidence_count is None:
            # Count both edge types: extraction emits REFERENCES, assert_claim
            # emits DERIVED_FROM. Either signals evidence for promotion.
            count_rows = await self._memgraph.execute_query(
                "MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})"
                "-[:REFERENCES|DERIVED_FROM]->() RETURN count(*) AS cnt",
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            evidence_count = int(count_rows[0]["cnt"]) if count_rows else 0

        prop_rows = await self._memgraph.execute_query(
            "MATCH (c:Claim {id: $claim_id, silo_id: $silo_id}) RETURN properties(c) AS props",
            {"claim_id": claim_id, "silo_id": silo_id},
        )
        if not prop_rows:
            return None

        claim_props: dict[str, Any] = dict(prop_rows[0]["props"])

        decision = evaluate_claim_for_fact(claim_props, evidence_count, corroborations)
        if not decision.should_promote:
            return None

        rule_value: str = decision.rule.value if decision.rule is not None else ""
        promoted_rows = await self._memgraph.execute_write(
            PROMOTE_CLAIM_TO_FACT,
            {"claim_id": claim_id, "silo_id": silo_id, "rule": rule_value},
        )

        if not promoted_rows:
            # WHERE NOT c:Fact filtered it out — already promoted
            already_rows = await self._memgraph.execute_query(
                "MATCH (c:Claim:Fact {id: $claim_id, silo_id: $silo_id}) RETURN properties(c) AS props",
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            return dict(already_rows[0]["props"]) if already_rows else None

        logger.info(
            "claim_promoted_to_fact",
            claim_id=claim_id,
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

        for about_ref in about:
            node_id_str = about_ref[5:] if about_ref.startswith("node:") else about_ref
            await self._memgraph.execute_write(
                """
                MATCH (c {id: $commitment_id}), (n {id: $node_id})
                MERGE (c)-[:ABOUT]->(n)
                """,
                {"commitment_id": str(node.id), "node_id": node_id_str},
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
        """Store a meta-observation (Meta-Memory layer)."""
        props = dict(metadata or {})
        props["observation_type"] = (
            observation_type.value if hasattr(observation_type, "value") else observation_type
        )
        props["about"] = about
        props["confidence"] = confidence
        if agent_id:
            props["agent_id"] = agent_id

        return await self.store(
            scope=scope,
            content=observation,
            node_type="MetaObservation",
            properties=props,
        )

    async def query(
        self,
        scope: ScopeContext,
        query: str,
        *,
        layers: list[Any] | None = None,
        filters: Any | None = None,
        top_k: int = 10,
        include_superseded: bool = False,
        as_of: datetime | None = None,  # noqa: ARG002
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

        Returns:
            List of QueryResult ordered by relevance.
        """
        if not self._embedding:
            logger.warning("query_no_embedding_service")
            return []

        query_vector = await self._embedding.embed_query(query)

        search_results = await self._qdrant.search(
            vector=query_vector,
            limit=top_k,
            silo_id=str(scope.silo_id),
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

        results: list[QueryResult] = []
        for node_id_str in result_ids:
            node = node_map.get(node_id_str)
            if node is None:
                continue

            props = node.properties or {}
            node_layer = props.get("layer", "memory")

            if layer_values and node_layer not in layer_values:
                continue

            node_confidence = float(props.get("confidence", 1.0))
            if min_confidence is not None and node_confidence < min_confidence:
                continue

            node_tags: list[str] = props.get("tags", [])
            if tags_filter and not any(t in node_tags for t in tags_filter):
                continue

            if not include_superseded and props.get("superseded_by"):
                continue

            results.append(
                QueryResult(
                    node_id=node.id,
                    layer=node_layer,
                    content=node.content,
                    confidence=node_confidence,
                    relevance_score=score_map[node_id_str],
                    summary=props.get("summary"),
                    tags=node_tags or None,
                    created_at=node.created_at,
                )
            )

        logger.info(
            "query_complete",
            query_len=len(query),
            result_count=len(results),
            silo_id=str(scope.silo_id),
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

        rows = await self._memgraph.execute_query(
            f"""
            UNWIND $start_ids AS seed_id
            MATCH (seed {{id: seed_id, silo_id: $silo_id}})
            OPTIONAL MATCH path = (seed)-[*1..{max_depth}]-(neighbor)
            WHERE neighbor.silo_id = $silo_id {layer_filter}
            WITH DISTINCT seed, neighbor
            UNWIND [seed] + COLLECT(neighbor) AS n
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
                           COALESCE(r.weight, 1.0) AS weight
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
