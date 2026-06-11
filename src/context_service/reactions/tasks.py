"""Taskiq task handlers for reaction event processing.

Each handler corresponds to a ReactionEventType. Handlers are registered onto
a broker via ``register_tasks(broker)``; the broker setup in broker.py calls
this so every silo-partitioned broker has the tasks in its local registry.

Handler design:
- Skeleton phase (Phase 8a): handlers that have a direct existing implementation
  call it; complex handlers (consolidate, check_synthesis, update_cluster_membership,
  propagate_confidence) are stubs that log and return. They will be filled in
  when the Dagster migration completes in Phase 9.
- All handlers use lazy service access via ``get_context_service()`` which
  requires worker bootstrap (Task 4 / worker.py) to call ``configure_services()``
  at startup before tasks execute.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import TYPE_CHECKING, Any

import structlog
from taskiq_redis import ListQueueBroker

from context_service.config.settings import settings
from context_service.reactions.events import ReactionEventType

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers for TX6 CONSENSUS
# ---------------------------------------------------------------------------


def _is_valid_uuid(value: str) -> bool:
    """Return True if ``value`` is a parseable UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _chains_reasoning_compatible(
    chain_a: Any,
    chain_b: Any,
    dtw_fn: Any,
    threshold: float = 0.5,
) -> bool:
    """Check if two ReasoningChainSteps have compatible reasoning paths via DTW.

    Uses step_embeddings from each chain. If either chain has no step embeddings,
    assumes compatibility (no information to contradict).

    Args:
        chain_a: First ReasoningChainSteps row.
        chain_b: Second ReasoningChainSteps row.
        dtw_fn: dtw_similarity function (injected for testability).
        threshold: Minimum DTW similarity score to consider compatible.

    Returns:
        True if compatible, False otherwise.
    """
    steps_a: list[list[float]] = []
    steps_b: list[list[float]] = []

    # Extract step_embeddings from the steps JSONB column if present.
    # The steps field is a list of dicts; step_embeddings may be stored
    # as a separate column (conclusion_embedding) or within each step dict.
    if chain_a.steps:
        steps_a = [s.get("embedding") for s in chain_a.steps if isinstance(s, dict) and s.get("embedding")]  # type: ignore[misc]
    if chain_b.steps:
        steps_b = [s.get("embedding") for s in chain_b.steps if isinstance(s, dict) and s.get("embedding")]  # type: ignore[misc]

    if not steps_a or not steps_b:
        # No step data; assume compatible (spec: "assume compatible")
        return True

    try:
        similarity = dtw_fn(steps_a, steps_b)
    except (ValueError, IndexError):
        # Dimension mismatch (e.g. embedding model changed) - assume compatible
        return True

    return bool(similarity > threshold)


async def _find_existing_consensus_fact(
    store: Any,  # noqa: ARG001
    conclusion_embedding: list[float],
    silo_id: str,
    threshold: float = 0.85,
) -> str | None:
    """Search for an existing consensus Fact with a similar conclusion.

    Queries Qdrant for Fact nodes whose conclusion embedding is close to the
    given embedding. Returns the node_id of the first match, or None.

    Args:
        store: Graph store (unused; Qdrant accessed directly via context service).
        conclusion_embedding: Conclusion vector to search against.
        silo_id: Tenant isolation identifier.
        threshold: Cosine similarity threshold.

    Returns:
        String UUID of matching Fact node, or None.
    """
    try:
        from qdrant_client.http import models as qdrant_models

        from context_service.mcp.server import get_context_service

        ctx_svc = get_context_service()
        client = await ctx_svc._qdrant._get_client()

        collections = await client.get_collections()
        collection_names = {c.name for c in collections.collections}
        if "context_vectors" not in collection_names:
            return None

        # Search for existing Fact nodes with similar content embeddings.
        # Fact nodes are stored in the main context_vectors collection.
        # Filter to Fact type so we don't confuse with other nodes.
        silo_collection = f"context_vectors_{silo_id.replace('-', '_')}"
        if silo_collection not in collection_names:
            # Try without silo prefix
            silo_collection = "context_vectors"

        response = await client.query_points(
            collection_name=silo_collection,
            query=conclusion_embedding,
            query_filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="silo_id",
                        match=qdrant_models.MatchValue(value=silo_id),
                    ),
                    qdrant_models.FieldCondition(
                        key="type",
                        match=qdrant_models.MatchValue(value="Fact"),
                    ),
                ]
            ),
            limit=1,
            score_threshold=threshold,
        )
        if response.points:
            point = response.points[0]
            if point.payload:
                return str(point.payload.get("node_id") or point.id)
    except Exception:
        logger.warning("find_existing_consensus_fact_error", silo_id=silo_id)

    return None


# Taskiq timeout labels (seconds) - passed as task labels for middleware
_TIMEOUT_EMBEDDING = 30
_TIMEOUT_LLM = 300
_TIMEOUT_SIMPLE = 10
_TIMEOUT_CASCADE = 60

# Confidence propagation threshold - only write back if delta exceeds this
_CONFIDENCE_DELTA_THRESHOLD = 0.1

# TX1 EXTRACT constants
_EXTRACTION_THRESHOLD = 200  # Minimum content length to trigger extraction
_MAX_CLAIMS_PER_MEMORY = 10  # Cap on claims extracted per memory
_SOURCE_TIER_DERIVED = 0.6  # Community/derived tier for extracted claims
_METHOD_WEIGHT_EXTRACTOR = 0.75  # Standard extractor method weight
_EXTRACTION_VERSION = "v1"  # Prompt/model version for re-extraction tracking
_EXTRACTION_SIMILARITY_THRESHOLD = 0.95  # Dedup threshold for similar claims


def register_tasks(broker: ListQueueBroker) -> None:
    """Register all reaction task handlers onto ``broker``.

    Called by ``broker._build_broker()`` so every silo broker has all tasks
    in its ``local_task_registry`` and ``find_task`` resolves correctly.

    Args:
        broker: The silo-specific Taskiq broker to register handlers on.
    """

    @broker.task(task_name=ReactionEventType.COMPUTE_EMBEDDING, timeout=_TIMEOUT_EMBEDDING)
    async def compute_embedding_task(node_id: str, silo_id: str, **_payload: Any) -> None:
        """Embed node content and upsert the vector to Qdrant.

        Fetches the node from the graph store, embeds its content via the
        embedding service, and writes the resulting vector to the Qdrant
        collection for the silo. No-ops if the node is missing or has no
        content.

        Args:
            node_id: String UUID of the node to embed.
            silo_id: Tenant isolation identifier.
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.COMPUTE_EMBEDDING
        )
        log.info("compute_embedding_task_start")

        from context_service.embeddings import build_embedding_service
        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("compute_embedding_services_not_configured")
            return

        store = ctx_svc.graph_store
        node_uuid = uuid.UUID(node_id)

        node = await store.get_node(node_uuid, silo_id)
        if node is None:
            log.warning("compute_embedding_node_not_found")
            return

        content = node.content
        if not content:
            log.debug("compute_embedding_no_content_skip")
            return

        embedder = build_embedding_service()
        vector = await embedder.embed_single(content)

        qdrant = ctx_svc.vector_store
        await qdrant.upsert(
            node_id=node_id,
            vector=vector,
            payload={"type": node.type},
            silo_id=silo_id,
        )
        log.info("compute_embedding_task_done", vector_length=len(vector), node_type=node.type)

    @broker.task(
        task_name=ReactionEventType.BATCH_COMPUTE_EMBEDDING,
        timeout=_TIMEOUT_EMBEDDING * 2,
    )
    async def batch_compute_embedding_task(items: list[dict[str, str]], **_payload: Any) -> None:
        """Embed a pre-collected batch of nodes and upsert vectors to Qdrant.

        Accepts a list of ``{"node_id": str, "silo_id": str}`` dicts, fetches
        each node from the graph store, embeds all non-empty content in a
        single batched call, and writes the resulting vectors to Qdrant.

        This task is invoked by the batch accumulator (or a scheduled job)
        rather than being enqueued by ``emit_reaction`` for individual nodes.
        The single-node ``compute_embedding_task`` is kept as a fallback for
        cases where a lone node must be embedded outside the normal flow.

        Args:
            items: List of dicts, each with ``node_id`` and ``silo_id`` keys.
            **_payload: Additional event payload (unused).
        """
        log = logger.bind(task=ReactionEventType.BATCH_COMPUTE_EMBEDDING, item_count=len(items))
        log.info("batch_compute_embedding_task_start")

        if not items:
            log.debug("batch_compute_embedding_task_empty_items_skip")
            return

        from context_service.embeddings import build_embedding_service
        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("batch_compute_embedding_services_not_configured")
            return

        store = ctx_svc.graph_store
        qdrant = ctx_svc.vector_store
        embedder = build_embedding_service()

        # Fetch all nodes; collect those with content.
        node_contents: list[tuple[str, str, str]] = []  # (node_id, silo_id, content)
        for item in items:
            node_id: str = item.get("node_id", "")
            silo_id: str = item.get("silo_id", "")
            if not node_id or not silo_id:
                log.warning("batch_compute_embedding_invalid_item_skip", item=item)
                continue

            node = await store.get_node(uuid.UUID(node_id), silo_id)
            if node is None:
                log.warning("batch_compute_embedding_node_not_found", node_id=node_id)
                continue

            if not node.content:
                log.debug("batch_compute_embedding_no_content_skip", node_id=node_id)
                continue

            node_contents.append((node_id, silo_id, node.content))

        if not node_contents:
            log.info("batch_compute_embedding_task_no_embeddable_nodes")
            return

        texts = [content for _, _, content in node_contents]
        vectors = await embedder.embed(texts)

        upserted = 0
        for (node_id, silo_id, _), vector in zip(node_contents, vectors, strict=True):
            await qdrant.upsert(
                node_id=node_id,
                vector=vector,
                payload={},
                silo_id=silo_id,
            )
            upserted += 1

        log.info(
            "batch_compute_embedding_task_done",
            requested=len(items),
            embeddable=len(node_contents),
            upserted=upserted,
        )

    @broker.task(task_name=ReactionEventType.UPDATE_HEAT, timeout=_TIMEOUT_SIMPLE)
    async def update_heat_task(
        node_id: str, silo_id: str, delta: float = 1.0, **_payload: Any
    ) -> None:
        """Increment the heat score of a node by ``delta``.

        Uses a direct Cypher write so the update is atomic and does not
        require a full node round-trip. ``delta`` defaults to 1.0 (one access).

        Args:
            node_id: String UUID of the node whose heat to update.
            silo_id: Tenant isolation identifier.
            delta: How much to add to the current heat score (default 1.0).
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.UPDATE_HEAT, delta=delta
        )
        log.info("update_heat_task_start")

        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("update_heat_services_not_configured")
            return

        store = ctx_svc.graph_store
        cypher = (
            "MATCH (n {id: $node_id, silo_id: $silo_id}) "
            "SET n.heat_score = coalesce(n.heat_score, 0.0) + $delta "
            "RETURN n.heat_score AS heat_score"
        )
        rows = await store.execute_write(
            cypher,
            {"node_id": node_id, "silo_id": silo_id, "delta": delta},
        )
        updated = rows[0]["heat_score"] if rows else None
        log.info("update_heat_task_done", heat_score=updated)

    @broker.task(task_name=ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP, timeout=_TIMEOUT_SIMPLE)
    async def update_cluster_membership_task(node_id: str, silo_id: str, **payload: Any) -> None:
        """Confirm cluster membership for a node after Dagster clustering has run.

        Full Leiden clustering is handled by the Dagster custodian job. This
        reactive handler runs after that job and:

        1. Resolves the cluster the node belongs to (via ``cluster_id`` payload
           hint or by querying the MEMBER_OF edge).
        2. Counts the cluster's current members.
        3. Emits CHECK_SYNTHESIS if the member count meets SYNTHESIS_THRESHOLD.

        No-ops silently if the node has no cluster membership.

        Args:
            node_id: String UUID of the node to check.
            silo_id: Tenant isolation identifier.
            **payload: Optional ``cluster_id`` hint from the triggering event.
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP
        )
        log.info("update_cluster_membership_task_start")

        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("update_cluster_membership_services_not_configured")
            return

        store = ctx_svc.graph_store

        # Use cluster_id from payload if provided; otherwise query the graph.
        cluster_id: str | None = payload.get("cluster_id")

        if not cluster_id:
            result = await store.execute_query(
                "MATCH (n {id: $node_id, silo_id: $silo_id})-[:MEMBER_OF]->(c:Cluster) "
                "RETURN c.id AS cluster_id LIMIT 1",
                {"node_id": node_id, "silo_id": silo_id},
            )
            if result:
                cluster_id = result[0].get("cluster_id")

        if not cluster_id:
            log.info("update_cluster_membership_no_cluster_found")
            return

        count_result = await store.execute_query(
            "MATCH (n)-[:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id}) "
            "RETURN count(n) AS member_count",
            {"cluster_id": cluster_id, "silo_id": silo_id},
        )
        member_count: int = count_result[0].get("member_count", 0) if count_result else 0

        log.info(
            "update_cluster_membership_counted",
            cluster_id=cluster_id,
            member_count=member_count,
        )

        from context_service.sage.transactions import SYNTHESIS_THRESHOLD

        if member_count >= SYNTHESIS_THRESHOLD:
            from context_service.reactions.events import ReactionEvent, emit_reaction

            event = ReactionEvent(
                event_type=ReactionEventType.CHECK_SYNTHESIS,
                node_id=node_id,
                silo_id=silo_id,
                payload={"cluster_id": cluster_id},
            )
            await emit_reaction(event)
            log.info("update_cluster_membership_synthesis_triggered", cluster_id=cluster_id)

        log.info("update_cluster_membership_task_done", cluster_id=cluster_id)

    @broker.task(task_name=ReactionEventType.CASCADE_STALENESS, timeout=_TIMEOUT_CASCADE)
    async def cascade_staleness_task(
        node_id: str, silo_id: str, depth: int = 1, **_payload: Any
    ) -> None:
        """Propagate staleness to dependent nodes.

        Delegates to ``sage.transactions.cascade_staleness`` which walks the
        dependency graph up to MAX_CASCADE_DEPTH and marks wisdom/knowledge
        nodes stale.

        Args:
            node_id: The node whose update should trigger staleness cascading.
            silo_id: Tenant isolation identifier.
            depth: Cascade depth to start from (default 1).
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.CASCADE_STALENESS, depth=depth
        )
        log.info("cascade_staleness_task_start")

        from context_service.mcp.server import get_context_service
        from context_service.sage.transactions import cascade_staleness

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("cascade_staleness_services_not_configured")
            return

        store = ctx_svc.graph_store
        marked = await cascade_staleness(store, node_id=node_id, silo_id=silo_id, depth=depth)
        log.info("cascade_staleness_task_done", nodes_marked=marked)

    @broker.task(task_name=ReactionEventType.FLAG_CONTRADICTION, timeout=_TIMEOUT_SIMPLE)
    async def flag_contradiction_task(
        node_id: str, silo_id: str, conflict_node_id: str | None = None, **_payload: Any
    ) -> None:
        """Mark a node as having an unresolved conflict and queue for consolidation.

        Sets ``conflict_status = 'unresolved'`` on the node, then emits a
        ``consolidate`` event if ``conflict_node_id`` is provided so the worker
        can resolve the pair.

        Args:
            node_id: Node involved in the contradiction.
            silo_id: Tenant isolation identifier.
            conflict_node_id: The other node in the conflict pair (optional).
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id,
            silo_id=silo_id,
            conflict_node_id=conflict_node_id,
            task=ReactionEventType.FLAG_CONTRADICTION,
        )
        log.info("flag_contradiction_task_start")

        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("flag_contradiction_services_not_configured")
            return

        store = ctx_svc.graph_store
        cypher = (
            "MATCH (n {id: $node_id, silo_id: $silo_id}) "
            "SET n.conflict_status = 'unresolved' "
            "RETURN n.id AS id"
        )
        await store.execute_write(cypher, {"node_id": node_id, "silo_id": silo_id})
        log.info("flag_contradiction_status_set")

        if conflict_node_id is not None:
            from context_service.reactions.events import ReactionEvent, emit_reaction

            consolidate_event = ReactionEvent(
                event_type=ReactionEventType.CONSOLIDATE,
                node_id=node_id,
                silo_id=silo_id,
                payload={"conflict_node_id": conflict_node_id},
            )
            await emit_reaction(consolidate_event)
            log.info("flag_contradiction_consolidate_queued", conflict_node_id=conflict_node_id)

    @broker.task(task_name=ReactionEventType.CONSOLIDATE, timeout=_TIMEOUT_LLM)
    async def consolidate_task(
        node_id: str, silo_id: str, conflict_node_id: str | None = None, **_payload: Any
    ) -> None:
        """Run the consolidation worker to resolve a conflict pair.

        Uses ``ConsolidationWorker.process_conflict`` which gathers signals,
        calls the deterministic resolver, and applies TX3 (supersede) or sets
        coexist status as appropriate.

        Args:
            node_id: First node in the conflict pair.
            silo_id: Tenant isolation identifier.
            conflict_node_id: Second node in the conflict pair.
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id,
            silo_id=silo_id,
            conflict_node_id=conflict_node_id,
            task=ReactionEventType.CONSOLIDATE,
        )
        log.info("consolidate_task_start")

        if conflict_node_id is None:
            log.warning("consolidate_task_missing_conflict_node_id_skip")
            return

        from context_service.mcp.server import get_context_service
        from context_service.sage.consolidation import ConsolidationWorker

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("consolidate_services_not_configured")
            return

        store = ctx_svc.graph_store
        worker = ConsolidationWorker()
        result = await worker.process_conflict(
            store=store,
            node_a_id=node_id,
            node_b_id=conflict_node_id,
            silo_id=silo_id,
        )
        log.info("consolidate_task_done", action=result.action, rationale=result.rationale)

    @broker.task(task_name=ReactionEventType.CHECK_SYNTHESIS, timeout=_TIMEOUT_LLM)
    async def check_synthesis_task(node_id: str, silo_id: str, **_payload: Any) -> None:
        """Trigger lazy synthesis if the node's cluster is ready.

        Looks up the clusters the node belongs to (or uses ``cluster_id`` from
        the payload if supplied), and for each cluster in READY state with at
        least SYNTHESIS_THRESHOLD active facts, calls
        ``sage.transactions.synthesize`` in async mode.

        Args:
            node_id: Node that triggered the synthesis check.
            silo_id: Tenant isolation identifier.
            **_payload: Optional ``cluster_id`` to target a specific cluster.
        """
        log = logger.bind(node_id=node_id, silo_id=silo_id, task=ReactionEventType.CHECK_SYNTHESIS)
        log.info("check_synthesis_task_start")

        from context_service.db import queries as q
        from context_service.embeddings import build_embedding_service
        from context_service.llm import build_llm_provider
        from context_service.mcp.server import get_context_service
        from context_service.sage.transactions import (
            SYNTHESIS_THRESHOLD,
            ClusterState,
            synthesize,
        )

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("check_synthesis_services_not_configured")
            return

        store = ctx_svc.graph_store

        # Resolve which cluster(s) to check.
        cluster_id_hint: str | None = _payload.get("cluster_id")

        cluster_rows = await store.execute_query(
            q.GET_NODE_CLUSTERS,
            {"node_id": node_id, "silo_id": silo_id},
        )

        if not cluster_rows:
            log.debug("check_synthesis_no_clusters_for_node")
            return

        for row in cluster_rows:
            cluster_node = row.get("c")
            if not cluster_node:
                continue

            cluster_id: str = cluster_node.get("id", "")
            if not cluster_id:
                continue

            # If the event carried a specific cluster_id, skip others.
            if cluster_id_hint is not None and cluster_id != cluster_id_hint:
                continue

            cluster_state = cluster_node.get("state", ClusterState.SPARSE.value)
            if cluster_state != ClusterState.READY.value:
                log.debug(
                    "check_synthesis_cluster_not_ready",
                    cluster_id=cluster_id,
                    state=cluster_state,
                )
                continue

            # Count active facts before acquiring the synthesis lock.
            facts_result = await store.execute_query(
                q.GET_FACTS_IN_CLUSTER,
                {"cluster_id": cluster_id, "silo_id": silo_id},
            )
            fact_count = len(facts_result) if facts_result else 0

            if fact_count < SYNTHESIS_THRESHOLD:
                log.debug(
                    "check_synthesis_below_threshold",
                    cluster_id=cluster_id,
                    fact_count=fact_count,
                    threshold=SYNTHESIS_THRESHOLD,
                )
                continue

            log.info(
                "check_synthesis_triggering",
                cluster_id=cluster_id,
                fact_count=fact_count,
            )

            try:
                from context_service.config.config_loader import load_config

                llm_config = load_config("llm")
                llm = build_llm_provider(
                    llm_config.get("provider", "litellm"),
                    llm_config.get("model"),
                )
                embedder = build_embedding_service()

                result, _events = await synthesize(
                    store,
                    cluster_id=cluster_id,
                    silo_id=silo_id,
                    llm=llm,
                    _embedder=embedder,
                    mode="async",
                )
                log.info(
                    "check_synthesis_done",
                    cluster_id=cluster_id,
                    belief_id=str(result.belief_id) if result.belief_id else None,
                    cluster_state=result.cluster_state,
                    fact_count=result.fact_count,
                )
            except Exception:
                log.exception("check_synthesis_synthesize_error", cluster_id=cluster_id)

    @broker.task(task_name=ReactionEventType.PROPAGATE_CONFIDENCE, timeout=_TIMEOUT_SIMPLE)
    async def propagate_confidence_task(node_id: str, silo_id: str, **_payload: Any) -> None:
        """Run incremental confidence propagation for a node.

        Fetches the depth-2 neighbourhood from the graph store, assembles the
        inputs required by ``propagate_incremental``, runs the computation, and
        writes back updated confidence values for nodes whose score changed by
        more than 0.1.

        Args:
            node_id: Node whose confidence neighbourhood to propagate.
            silo_id: Tenant isolation identifier.
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.PROPAGATE_CONFIDENCE
        )
        log.info("propagate_confidence_task_start")

        from context_service.mcp.server import get_context_service
        from context_service.sage.epistemology import propagate_incremental

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("propagate_confidence_services_not_configured")
            return

        store = ctx_svc.graph_store

        # Fetch depth-2 neighbourhood including all relevant edges.
        # Each row may contain one support_edge or one contra_edge (or neither).
        neighborhood_query = """
MATCH (target {id: $node_id, silo_id: $silo_id})
CALL {
    WITH target
    MATCH path = (target)-[*1..2]-(neighbor)
    WHERE neighbor.silo_id = $silo_id
    RETURN DISTINCT neighbor
}
WITH target, collect(neighbor) + [target] AS nodes
UNWIND nodes AS n
OPTIONAL MATCH (n)-[support:SUPPORTS|SYNTHESIZED_FROM]->(other)
WHERE other IN nodes
OPTIONAL MATCH (n)-[contra:CONTRADICTS]->(other2)
WHERE other2 IN nodes
RETURN
    n.id AS node_id,
    n.credibility AS credibility,
    CASE WHEN support IS NOT NULL
        THEN [startNode(support).id, endNode(support).id, coalesce(support.weight, 1.0)]
        ELSE null
    END AS support_edge,
    CASE WHEN contra IS NOT NULL
        THEN [startNode(contra).id, endNode(contra).id, coalesce(contra.weight, 1.0)]
        ELSE null
    END AS contra_edge
"""
        rows = await store.execute_query(
            neighborhood_query, {"node_id": node_id, "silo_id": silo_id}
        )

        if not rows:
            log.warning("propagate_confidence_no_neighborhood_found")
            return

        # Build input structures from query results. Rows are deduplicated per
        # node but may repeat due to multiple edges, so use dicts/sets.
        node_credibility: dict[str, float] = {}
        support_edges_set: set[tuple[str, str, float]] = set()
        contradiction_edges_set: set[tuple[str, str, float]] = set()

        for row in rows:
            nid = row.get("node_id")
            if nid and nid not in node_credibility:
                raw_cred = row.get("credibility")
                node_credibility[nid] = float(raw_cred) if raw_cred is not None else 0.5

            support_edge = row.get("support_edge")
            if support_edge:
                support_edges_set.add(
                    (str(support_edge[0]), str(support_edge[1]), float(support_edge[2]))
                )

            contra_edge = row.get("contra_edge")
            if contra_edge:
                contradiction_edges_set.add(
                    (str(contra_edge[0]), str(contra_edge[1]), float(contra_edge[2]))
                )

        node_ids = list(node_credibility.keys())
        support_edges_list = list(support_edges_set)
        contradiction_edges_list = list(contradiction_edges_set)

        log.debug(
            "propagate_confidence_inputs",
            neighborhood_size=len(node_ids),
            support_edges=len(support_edges_list),
            contradiction_edges=len(contradiction_edges_list),
        )

        updated_scores = propagate_incremental(
            target_id=node_id,
            node_ids=node_ids,
            credibility_scores=node_credibility,
            support_edges=support_edges_list,
            contradiction_edges=contradiction_edges_list,
        )

        # Write back nodes whose confidence changed significantly.
        update_query = (
            "MATCH (n {id: $node_id, silo_id: $silo_id}) "
            "SET n.confidence = $confidence "
            "RETURN n.id AS id"
        )
        updated_count = 0
        for affected_id, new_conf in updated_scores.items():
            old_conf = node_credibility.get(affected_id, 0.5)
            if abs(new_conf - old_conf) > _CONFIDENCE_DELTA_THRESHOLD:
                await store.execute_write(
                    update_query,
                    {"node_id": affected_id, "silo_id": silo_id, "confidence": new_conf},
                )
                updated_count += 1

        log.info(
            "propagate_confidence_task_done",
            affected_nodes=len(updated_scores),
            updated_nodes=updated_count,
        )

    @broker.task(task_name=ReactionEventType.CHECK_EXTRACTION_TRIGGER, timeout=_TIMEOUT_LLM)
    async def extract_claims_task(node_id: str, silo_id: str, **_payload: Any) -> None:
        """Extract structured claims from Memory content (TX1 EXTRACT).

        Transforms unstructured Memory content into Knowledge (Claims) by:
        1. Checking content length exceeds threshold
        2. Using LLM to extract verifiable propositions
        3. Deduplicating against existing claims via CORROBORATES edges
        4. Creating new Claims with CITE v2 credibility scaling
        5. Linking via EXTRACTED_FROM edges

        Args:
            node_id: String UUID of the Memory node to extract from.
            silo_id: Tenant isolation identifier.
            **_payload: Additional event payload (unused).
        """
        import json
        import time

        from primitives.schema.edges import CITEEdgeType
        from primitives.schema.labels import PersistenceLayer, layer_for_label

        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.CHECK_EXTRACTION_TRIGGER
        )
        log.info("extract_claims_task_start")
        start_time = time.perf_counter()

        from context_service.embeddings import build_embedding_service
        from context_service.engine.models import BinaryEdge
        from context_service.llm import build_llm_provider
        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("extract_claims_services_not_configured")
            return

        store = ctx_svc.graph_store
        qdrant = ctx_svc.vector_store
        node_uuid = uuid.UUID(node_id)

        # 1. Fetch source node
        node = await store.get_node(node_uuid, silo_id)
        if node is None:
            log.warning("extract_claims_node_not_found")
            return

        # Check if Memory layer
        try:
            node_layer = layer_for_label(node.type)
        except ValueError:
            log.debug("extract_claims_unknown_label_skip", label=node.type)
            return

        if node_layer != PersistenceLayer.MEMORY:
            log.debug("extract_claims_not_memory_skip", layer=str(node_layer))
            return

        content = node.content or ""
        if len(content) < _EXTRACTION_THRESHOLD:
            log.debug("extract_claims_content_too_short", length=len(content))
            return

        # 2. Check idempotency
        props = node.properties or {}
        if props.get("extracted_at") and props.get("extraction_version") == _EXTRACTION_VERSION:
            log.debug("extract_claims_already_extracted")
            return

        # 3. LLM extraction
        llm = build_llm_provider(settings.llm_provider, settings.default_llm_model)
        extraction_prompt = f"""Extract verifiable claims from this observation. Each claim should be:
- A single factual proposition
- Independently verifiable
- Not an opinion or speculation

Observation:
{content}

Return a JSON array of claims:
[
  {{"content": "claim text", "raw_confidence": 0.0-1.0}},
  ...
]

Return only valid JSON, no other text."""

        try:
            messages = [{"role": "user", "content": extraction_prompt}]
            response, _usage = await llm.complete(messages)
            claims_data = json.loads(response.strip())
            if not isinstance(claims_data, list):
                claims_data = []
        except (json.JSONDecodeError, Exception) as e:
            log.warning("extract_claims_llm_error", error=str(e))
            return

        claims_data = claims_data[:_MAX_CLAIMS_PER_MEMORY]
        log.debug("extract_claims_llm_returned", count=len(claims_data))

        # 4. Process each claim
        embedder = build_embedding_service()
        claims_created = 0
        corroborates_created = 0

        for claim_item in claims_data:
            claim_content = claim_item.get("content", "")
            raw_confidence = float(claim_item.get("raw_confidence", 0.5))

            if not claim_content:
                continue

            # Check for existing similar claim (dedup) - filter to Claims only
            from qdrant_client import models as qdrant_models

            claim_embedding = await embedder.embed_single(claim_content)
            similar_results = await qdrant.search(
                vector=claim_embedding,
                limit=1,
                score_threshold=_EXTRACTION_SIMILARITY_THRESHOLD,
                silo_id=silo_id,
                filter_conditions=[
                    qdrant_models.FieldCondition(
                        key="type",
                        match=qdrant_models.MatchValue(value="Claim"),
                    ),
                ],
            )

            if similar_results:
                # Create CORROBORATES edge instead of duplicate
                # Use node_id from payload, not Qdrant point id
                result = similar_results[0]
                existing_id = (
                    result.payload.get("node_id") if hasattr(result, "payload") and result.payload
                    else getattr(result, "id", None)
                )
                if existing_id:
                    await store.upsert_binary_edge(
                        BinaryEdge(
                            source_id=uuid.UUID(node_id),
                            target_id=uuid.UUID(str(existing_id)),
                            type=CITEEdgeType.CORROBORATES.value,
                            silo_id=uuid.UUID(silo_id),
                            properties={"source": "extraction", "independence": 0.3},
                        ),
                        silo_id=silo_id,
                    )
                    corroborates_created += 1
                continue

            # Create new claim with credibility scaling per CITE v2
            # credibility = source_tier * method_weight * raw_confidence
            # Caps extracted claims at ~0.45 (below agent claims at 0.8 * 1.0 = 0.8)
            scaled_confidence = _SOURCE_TIER_DERIVED * _METHOD_WEIGHT_EXTRACTOR * raw_confidence

            from context_service.sage.transactions import store_claim

            claim_result, _events = await store_claim(
                store=store,
                content=claim_content,
                evidence_refs=[f"engrammic://node/{node_id}"],
                silo_id=silo_id,
                agent_id="system:extractor",
                source_tier="community",
                confidence=scaled_confidence,
            )

            if claim_result.node_id:
                # Create EXTRACTED_FROM edge
                await store.upsert_binary_edge(
                    BinaryEdge(
                        source_id=claim_result.node_id,
                        target_id=node_uuid,
                        type=CITEEdgeType.EXTRACTED_FROM.value,
                        silo_id=uuid.UUID(silo_id),
                    ),
                    silo_id=silo_id,
                )
                claims_created += 1

        # 5. Mark as extracted
        from datetime import UTC, datetime

        mark_query = """
MATCH (n {id: $node_id, silo_id: $silo_id})
SET n.extracted_at = $extracted_at, n.extraction_version = $version
RETURN n.id
"""
        await store.execute_write(
            mark_query,
            {
                "node_id": node_id,
                "silo_id": silo_id,
                "extracted_at": datetime.now(UTC).isoformat(),
                "version": _EXTRACTION_VERSION,
            },
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.info(
            "extract_claims_task_done",
            claims_created=claims_created,
            corroborates_created=corroborates_created,
            content_length=len(content),
            latency_ms=round(elapsed_ms, 2),
        )

    @broker.task(task_name=ReactionEventType.TRACE_REASONING, timeout=_TIMEOUT_SIMPLE)
    async def trace_reasoning_task(
        node_id: str, silo_id: str, session_id: str | None = None, **_payload: Any
    ) -> None:
        """Persist uncommitted WorkingHypotheses as ReasoningChains (TX7 TRACE).

        At session end, collects all uncommitted hypotheses for the session,
        persists each as a ReasoningChainSteps row in Postgres, creates a
        TRACED_FROM edge in the graph, and emits CHECK_CONSENSUS for each chain
        so TX6 can check for multi-agent agreement.

        Args:
            node_id: Session node id (ReasoningSession graph node) or any node
                     that triggered the session-end event. Used as the graph
                     anchor; typically the session's representative node.
            silo_id: Tenant isolation identifier.
            session_id: Optional override. If omitted, falls back to node_id as
                        the session_id so callers that emit the session node id
                        directly still work.
            **_payload: Additional event payload (unused).
        """
        import time as _time
        from datetime import datetime

        start_time = _time.perf_counter()

        effective_session_id = session_id or node_id

        log = logger.bind(
            node_id=node_id,
            silo_id=silo_id,
            session_id=effective_session_id,
            task=ReactionEventType.TRACE_REASONING,
        )
        log.info("trace_reasoning_task_start")

        from primitives.schema.edges import CITEEdgeType

        from context_service.db.postgres import get_session as get_pg_session
        from context_service.db.queries import GET_WORKING_HYPOTHESES_FOR_SESSION
        from context_service.engine.models import BinaryEdge
        from context_service.mcp.server import get_context_service
        from context_service.models.postgres.reasoning import ReasoningChainSteps

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("trace_reasoning_services_not_configured")
            return

        store = ctx_svc.graph_store

        # Fetch all uncommitted WorkingHypotheses for this session.
        rows = await store.execute_query(
            GET_WORKING_HYPOTHESES_FOR_SESSION,
            {"session_id": effective_session_id, "silo_id": silo_id},
        )

        if not rows:
            log.info("trace_reasoning_no_hypotheses_found")
            return

        # Filter to uncommitted and untraced hypotheses only.
        uncommitted = [
            r for r in rows
            if not r.get("crystallized_into") and not r.get("traced_at")
        ]

        if not uncommitted:
            log.info("trace_reasoning_all_hypotheses_committed")
            return

        log.info("trace_reasoning_uncommitted_count", count=len(uncommitted))

        silo_uuid = uuid.UUID(silo_id)
        now = datetime.now(UTC)
        chains_traced: list[str] = []

        from context_service.embeddings import build_embedding_service
        from primitives.schema.labels import IntelligenceLabel

        embedder = build_embedding_service()

        for row in uncommitted:
            hypothesis_id_str: str = row.get("belief_id", "")
            content: str = row.get("content", "") or ""
            confidence: float = float(row.get("confidence") or 0.5)
            agent_id: str | None = row.get("agent_id")

            if not hypothesis_id_str:
                log.warning("trace_reasoning_missing_belief_id_skip")
                continue

            hypothesis_uuid = uuid.UUID(hypothesis_id_str)
            chain_id = uuid.uuid4()

            # 1. Embed conclusion for Qdrant and Postgres.
            conclusion_embedding: list[float] | None = None
            try:
                conclusion_embedding = await embedder.embed_single(content)
            except Exception:
                log.exception(
                    "trace_reasoning_embed_error",
                    hypothesis_id=hypothesis_id_str,
                )

            # 2. Persist ReasoningChainSteps row in Postgres.
            try:
                async with get_pg_session() as pg_session:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert

                    stmt = pg_insert(ReasoningChainSteps).values(
                        chain_id=chain_id,
                        silo_id=silo_uuid,
                        steps=[{"content": content, "confidence": confidence}],
                        conclusion=content,
                        conclusion_embedding=conclusion_embedding,
                        agent_id=agent_id,
                        source_hypothesis_id=hypothesis_uuid,
                        traced_at=now,
                    )
                    stmt = stmt.on_conflict_do_nothing(index_elements=["chain_id"])
                    await pg_session.execute(stmt)
            except Exception:
                log.exception(
                    "trace_reasoning_postgres_write_error",
                    hypothesis_id=hypothesis_id_str,
                    chain_id=str(chain_id),
                )
                continue

            # 3. Create stub ReasoningChain node in graph (required for edges).
            create_node_cypher = f"""
CREATE (n:Node:{IntelligenceLabel.REASONING_CHAIN} {{
    id: $id,
    type: $type,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    properties: $props
}})
RETURN n.id AS id
"""
            try:
                await store.execute_write(
                    create_node_cypher,
                    {
                        "id": str(chain_id),
                        "type": IntelligenceLabel.REASONING_CHAIN.value,
                        "silo_id": silo_id,
                        "content": content,
                        "created_at": now.isoformat(),
                        "props": {
                            "layer": "intelligence",
                            "state": "ACTIVE",
                            "agent_id": agent_id,
                            "source_hypothesis_id": hypothesis_id_str,
                            "confidence": confidence,
                        },
                    },
                )
            except Exception:
                log.exception(
                    "trace_reasoning_graph_node_error",
                    hypothesis_id=hypothesis_id_str,
                    chain_id=str(chain_id),
                )

            # 4. Upsert conclusion embedding to Qdrant for TX6 search.
            if conclusion_embedding:
                try:
                    from qdrant_client.http import models as qdrant_models

                    qdrant_client = await ctx_svc._qdrant._get_client()
                    await qdrant_client.upsert(
                        collection_name="reasoning_chains",
                        points=[
                            qdrant_models.PointStruct(
                                id=str(chain_id),
                                vector=conclusion_embedding,
                                payload={
                                    "silo_id": silo_id,
                                    "type": IntelligenceLabel.REASONING_CHAIN.value,
                                    "agent_id": agent_id,
                                    "node_id": str(chain_id),
                                },
                            )
                        ],
                    )
                except Exception:
                    log.exception(
                        "trace_reasoning_qdrant_error",
                        chain_id=str(chain_id),
                    )

            # 5. Create TRACED_FROM edge: ReasoningChain -> WorkingHypothesis.
            try:
                edge = BinaryEdge(
                    source_id=chain_id,
                    target_id=hypothesis_uuid,
                    type="TRACED_FROM",
                    silo_id=silo_uuid,
                    properties={"traced_at": now.isoformat()},
                )
                await store.upsert_binary_edge(edge, silo_id)
            except Exception:
                log.exception(
                    "trace_reasoning_edge_write_error",
                    hypothesis_id=hypothesis_id_str,
                    chain_id=str(chain_id),
                )

            chains_traced.append(str(chain_id))
            log.debug(
                "trace_reasoning_chain_persisted",
                hypothesis_id=hypothesis_id_str,
                chain_id=str(chain_id),
            )

        # Mark hypotheses as traced in the graph.
        if chains_traced:
            mark_cypher = (
                "MATCH (wb:WorkingHypothesis {session_id: $session_id, silo_id: $silo_id}) "
                "SET wb.traced_at = $traced_at "
                "RETURN count(wb) AS marked"
            )
            await store.execute_write(
                mark_cypher,
                {
                    "session_id": effective_session_id,
                    "silo_id": silo_id,
                    "traced_at": now.isoformat(),
                },
            )

            # Emit CHECK_CONSENSUS for each traced chain (gated by trace_on_commit).
            if settings.consensus.trace_on_commit:
                from context_service.reactions.events import ReactionEvent, emit_reaction

                for chain_id_str in chains_traced:
                    consensus_event = ReactionEvent(
                        event_type=ReactionEventType.CHECK_CONSENSUS,
                        node_id=chain_id_str,
                        silo_id=silo_id,
                        payload={"session_id": effective_session_id},
                    )
                    await emit_reaction(consensus_event)

        elapsed_ms = (_time.perf_counter() - start_time) * 1000
        log.info(
            "trace_reasoning_task_done",
            chains_traced=len(chains_traced),
            hypotheses_found=len(uncommitted),
            latency_ms=round(elapsed_ms, 2),
        )

    # ---------------------------------------------------------------------------
    # TX6 CONSENSUS constants
    # ---------------------------------------------------------------------------
    _CONSENSUS_THRESHOLD_K = settings.consensus.min_chains
    _CONSENSUS_THRESHOLD_J = settings.consensus.min_agents
    _CONSENSUS_CONCLUSION_THRESHOLD = settings.consensus.conclusion_threshold
    _CONSENSUS_REASONING_THRESHOLD = settings.consensus.reasoning_threshold
    _CONSENSUS_SEARCH_LIMIT = 20  # Max candidates from ANN search

    @broker.task(task_name=ReactionEventType.CHECK_CONSENSUS, timeout=15)
    async def check_consensus_task(
        node_id: str, silo_id: str, **_payload: Any
    ) -> None:
        """Check if a reasoning chain participates in consensus, promote to Fact if so (TX6).

        Implements three-layer consensus detection:
        1. Conclusion similarity via Qdrant ANN (threshold 0.85)
        2. Reasoning compatibility via DTW on step embeddings
        3. Agent diversity: >= J distinct agents required

        If K chains from J agents agree, creates a Fact node with PROMOTED_FROM
        (for INV2) and CONSENSUS_FROM (for provenance) edges to all supporting
        chains. Triggers downstream COMPUTE_EMBEDDING and UPDATE_CLUSTER_MEMBERSHIP
        reactions.

        If consensus already exists for this conclusion, extends it by adding
        edges from the existing Fact to this chain.

        Args:
            node_id: String UUID of the ReasoningChain that triggered the check.
            silo_id: Tenant isolation identifier.
            **_payload: Additional event payload (unused).
        """
        import time as _time
        from datetime import datetime

        start_time = _time.perf_counter()
        chain_id = node_id  # node_id carries the chain_id for CHECK_CONSENSUS events

        log = logger.bind(
            node_id=chain_id,
            silo_id=silo_id,
            task=ReactionEventType.CHECK_CONSENSUS,
        )
        log.info("check_consensus_task_start")

        from primitives.schema.edges import CITEEdgeType
        from primitives.schema.labels import KnowledgeLabel
        from sqlalchemy import select

        from context_service.db.postgres import get_session as get_pg_session
        from context_service.engine.models import BinaryEdge
        from context_service.mcp.server import get_context_service
        from context_service.models.postgres.reasoning import ReasoningChainSteps
        from context_service.reactions.events import ReactionEvent, emit_reaction

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("check_consensus_services_not_configured")
            return

        store = ctx_svc.graph_store

        # 1. Fetch the triggering chain from Postgres.
        chain_uuid = uuid.UUID(chain_id)
        silo_uuid = uuid.UUID(silo_id)
        chain: ReasoningChainSteps | None = None

        try:
            async with get_pg_session() as pg:
                result = await pg.execute(
                    select(ReasoningChainSteps).where(
                        ReasoningChainSteps.chain_id == chain_uuid,
                        ReasoningChainSteps.silo_id == silo_uuid,
                    )
                )
                chain = result.scalar_one_or_none()
        except Exception:
            log.exception("check_consensus_chain_fetch_error", chain_id=chain_id)
            return

        if chain is None or not chain.conclusion:
            log.info("check_consensus_chain_not_found_or_no_conclusion", chain_id=chain_id)
            return

        # 2. Embed conclusion if not already stored.
        conclusion_embedding: list[float] | None = chain.conclusion_embedding

        if conclusion_embedding is None:
            from context_service.embeddings import build_embedding_service

            try:
                embedder = build_embedding_service()
                conclusion_embedding = await embedder.embed_single(chain.conclusion)

                # Persist the conclusion embedding for future consensus checks.
                async with get_pg_session() as pg:
                    stmt_chain = await pg.get(ReasoningChainSteps, chain_uuid)
                    if stmt_chain is not None:
                        stmt_chain.conclusion_embedding = conclusion_embedding
            except Exception:
                log.exception("check_consensus_embed_error", chain_id=chain_id)
                return

        # 3. Find similar conclusions via Qdrant ANN (Layer 1).
        from context_service.engine.chain_applicability import search_chains

        similar_raw = await search_chains(
            query_embedding=conclusion_embedding,
            top_k=_CONSENSUS_SEARCH_LIMIT,
            threshold=_CONSENSUS_CONCLUSION_THRESHOLD,
            silo_id=silo_id,
        )

        # Exclude the triggering chain itself.
        similar_raw = [r for r in similar_raw if r["id"] != chain_id]

        if not similar_raw:
            log.debug("check_consensus_no_similar_chains", chain_id=chain_id)
            return

        # Fetch Postgres rows for all similar candidates.
        candidate_ids = [uuid.UUID(r["id"]) for r in similar_raw if _is_valid_uuid(r["id"])]
        candidates: list[ReasoningChainSteps] = []

        if candidate_ids:
            try:
                async with get_pg_session() as pg:
                    result = await pg.execute(
                        select(ReasoningChainSteps).where(
                            ReasoningChainSteps.chain_id.in_(candidate_ids),
                            ReasoningChainSteps.silo_id == silo_uuid,
                        )
                    )
                    candidates = list(result.scalars().all())
            except Exception:
                log.exception("check_consensus_candidate_fetch_error")
                return

        # 4. Filter by reasoning compatibility via DTW (Layer 2).
        from context_service.engine.dtw import dtw_similarity

        compatible: list[ReasoningChainSteps] = []
        for candidate in candidates:
            if _chains_reasoning_compatible(
                chain, candidate, dtw_similarity, threshold=_CONSENSUS_REASONING_THRESHOLD
            ):
                compatible.append(candidate)

        # 5. Check thresholds: K chains from J agents.
        all_chains = [chain] + compatible
        unique_agents = {c.agent_id for c in all_chains if c.agent_id is not None}

        log.debug(
            "check_consensus_thresholds",
            chain_count=len(all_chains),
            agent_count=len(unique_agents),
            required_chains=_CONSENSUS_THRESHOLD_K,
            required_agents=_CONSENSUS_THRESHOLD_J,
        )

        if len(all_chains) < _CONSENSUS_THRESHOLD_K:
            log.info(
                "check_consensus_insufficient_chains",
                chain_count=len(all_chains),
                required=_CONSENSUS_THRESHOLD_K,
            )
            return

        if len(unique_agents) < _CONSENSUS_THRESHOLD_J:
            log.info(
                "check_consensus_insufficient_agents",
                agent_count=len(unique_agents),
                required=_CONSENSUS_THRESHOLD_J,
            )
            return

        # 6. Check if consensus Fact already exists for this conclusion.
        existing_fact_id: str | None = await _find_existing_consensus_fact(
            store, conclusion_embedding, silo_id
        )

        if existing_fact_id is not None:
            # Extend existing consensus: add edges from existing Fact to this chain.
            try:
                for edge_type in ("PROMOTED_FROM", "CONSENSUS_FROM"):
                    edge = BinaryEdge(
                        source_id=uuid.UUID(existing_fact_id),
                        target_id=chain_uuid,
                        type=edge_type,
                        silo_id=silo_uuid,
                        properties={"extended_at": datetime.now(UTC).isoformat()},
                    )
                    await store.upsert_binary_edge(edge, silo_id)

                log.info(
                    "check_consensus_extended",
                    fact_id=existing_fact_id,
                    chain_id=chain_id,
                )
            except Exception:
                log.exception(
                    "check_consensus_extend_edge_error",
                    fact_id=existing_fact_id,
                    chain_id=chain_id,
                )
            return

        # 7. Create new Fact from consensus.
        agent_count = len(unique_agents)
        base_confidence = min(
            0.95, 0.6 + (len(all_chains) * 0.05) + (agent_count * 0.1)
        )
        now = datetime.now(UTC)

        fact_cypher = f"""
CREATE (n:Node:{KnowledgeLabel.FACT} {{
    id: $id,
    type: $type,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    updated_at: $updated_at,
    valid_from: $valid_from,
    properties: $props,
    committed: true,
    version: 1
}})
RETURN n.id AS id
"""
        fact_id = uuid.uuid4()
        fact_props: dict[str, Any] = {
            "layer": "knowledge",
            "state": "active",
            "source": "consensus",
            "chain_count": len(all_chains),
            "agent_count": agent_count,
            "confidence": base_confidence,
        }

        try:
            await store.execute_write(
                fact_cypher,
                {
                    "id": str(fact_id),
                    "type": KnowledgeLabel.FACT,
                    "silo_id": silo_id,
                    "content": chain.conclusion,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "valid_from": now.isoformat(),
                    "props": fact_props,
                },
            )
        except Exception:
            log.exception("check_consensus_fact_create_error", fact_id=str(fact_id))
            return

        # 8. Create PROMOTED_FROM + CONSENSUS_FROM edges to all supporting chains.
        edge_errors = 0
        for supporting_chain in all_chains:
            supporting_chain_uuid = supporting_chain.chain_id
            for edge_type in ("PROMOTED_FROM", "CONSENSUS_FROM"):
                try:
                    edge = BinaryEdge(
                        source_id=fact_id,
                        target_id=supporting_chain_uuid,
                        type=edge_type,
                        silo_id=silo_uuid,
                        properties={"created_at": now.isoformat()},
                    )
                    await store.upsert_binary_edge(edge, silo_id)
                except Exception:
                    log.exception(
                        "check_consensus_edge_write_error",
                        fact_id=str(fact_id),
                        chain_id=str(supporting_chain_uuid),
                        edge_type=str(edge_type),
                    )
                    edge_errors += 1

        # 9. Trigger downstream reactions.
        for downstream_event_type in (
            ReactionEventType.COMPUTE_EMBEDDING,
            ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP,
        ):
            downstream_event = ReactionEvent(
                event_type=downstream_event_type,
                node_id=str(fact_id),
                silo_id=silo_id,
            )
            await emit_reaction(downstream_event)

        elapsed_ms = (_time.perf_counter() - start_time) * 1000
        log.info(
            "check_consensus_task_done",
            fact_id=str(fact_id),
            chain_count=len(all_chains),
            agent_count=agent_count,
            edge_errors=edge_errors,
            latency_ms=round(elapsed_ms, 2),
        )

    # ---------------------------------------------------------------------------
    # TX11 CHAIN_TOMBSTONED constants
    # ---------------------------------------------------------------------------
    _CONSENSUS_MIN_CHAINS = settings.consensus.min_chains  # Minimum supporting chains for a consensus Fact to remain valid

    @broker.task(task_name=ReactionEventType.CHAIN_TOMBSTONED, timeout=_TIMEOUT_CASCADE)
    async def chain_tombstoned_task(
        node_id: str, silo_id: str, **_payload: Any
    ) -> None:
        """Cascade staleness to consensus Facts when a ReasoningChain is tombstoned (TX11).

        When a ReasoningChain is tombstoned:
        1. Finds all Facts with a CONSENSUS_FROM edge pointing to the chain.
        2. For each Fact, counts the remaining active (non-tombstoned) chains via
           CONSENSUS_FROM edges.
        3. Emits CASCADE_STALENESS for every such Fact.
        4. If remaining active chains fall below CONSENSUS_MIN_CHAINS, tombstones
           the Fact directly (soft-delete, same cancel-window pattern as TX15).

        Args:
            node_id: String UUID of the tombstoned ReasoningChain.
            silo_id: Tenant isolation identifier.
            **_payload: Additional event payload (unused).
        """
        import time as _time

        start_time = _time.perf_counter()
        chain_id = node_id

        log = logger.bind(
            node_id=chain_id,
            silo_id=silo_id,
            task=ReactionEventType.CHAIN_TOMBSTONED,
        )
        log.info("chain_tombstoned_task_start")

        from context_service.mcp.server import get_context_service
        from context_service.reactions.events import ReactionEvent, emit_reaction

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("chain_tombstoned_services_not_configured")
            return

        store = ctx_svc.graph_store

        # 1. Find all Facts that reference this chain via CONSENSUS_FROM.
        #    Direction: Fact -[:EDGE {type: 'CONSENSUS_FROM'}]-> ReasoningChain
        facts_query = (
            "MATCH (f:Fact)-[e:EDGE]->(c {id: $chain_id, silo_id: $silo_id}) "
            "WHERE e.type = 'CONSENSUS_FROM' "
            "RETURN f.id AS fact_id, f.properties.state AS fact_state"
        )
        fact_rows = await store.execute_query(
            facts_query,
            {"chain_id": chain_id, "silo_id": silo_id},
        )

        if not fact_rows:
            log.info("chain_tombstoned_no_consensus_facts", chain_id=chain_id)
            return

        log.info("chain_tombstoned_facts_found", count=len(fact_rows), chain_id=chain_id)

        facts_staled = 0
        facts_tombstoned = 0

        for row in fact_rows:
            fact_id: str | None = row.get("fact_id")
            fact_state: str | None = row.get("fact_state")

            if not fact_id:
                continue

            # Skip Facts already tombstoned or deleted.
            if fact_state in ("TOMBSTONED", "DELETED"):
                log.debug(
                    "chain_tombstoned_fact_skip_inactive",
                    fact_id=fact_id,
                    fact_state=fact_state,
                )
                continue

            # 2. Count remaining active chains for this Fact.
            remaining_query = (
                "MATCH (f {id: $fact_id, silo_id: $silo_id})-[e:EDGE]->(c) "
                "WHERE e.type = 'CONSENSUS_FROM' AND c.id <> $chain_id "
                "AND (c.properties.state IS NULL OR c.properties.state = 'ACTIVE') "
                "RETURN count(c) AS remaining_count"
            )
            remaining_rows = await store.execute_query(
                remaining_query,
                {"fact_id": fact_id, "silo_id": silo_id, "chain_id": chain_id},
            )
            remaining_count: int = (
                remaining_rows[0].get("remaining_count", 0) if remaining_rows else 0
            )

            log.debug(
                "chain_tombstoned_remaining_chains",
                fact_id=fact_id,
                remaining_count=remaining_count,
                min_required=_CONSENSUS_MIN_CHAINS,
            )

            # 3. Always emit CASCADE_STALENESS for the Fact.
            stale_event = ReactionEvent(
                event_type=ReactionEventType.CASCADE_STALENESS,
                node_id=fact_id,
                silo_id=silo_id,
                payload={"reason": "chain_tombstoned", "chain_id": chain_id},
            )
            await emit_reaction(stale_event)
            facts_staled += 1

            # 4. If remaining chains drop below threshold, tombstone the Fact.
            if remaining_count < _CONSENSUS_MIN_CHAINS:
                from datetime import timedelta

                from context_service.sage.transactions import CANCEL_WINDOW_DURATION_SECONDS

                from datetime import datetime as _datetime

                now = _datetime.now(UTC)
                cancel_window_expires = now + timedelta(seconds=CANCEL_WINDOW_DURATION_SECONDS)

                tombstone_query = (
                    "MATCH (f {id: $fact_id, silo_id: $silo_id}) "
                    "WHERE NOT f.properties.state IN ['TOMBSTONED', 'DELETED'] "
                    "SET f.properties.state = 'TOMBSTONED', "
                    "    f.properties.tombstoned_at = $tombstoned_at, "
                    "    f.properties.tombstone_reason = 'consensus_chain_count_below_threshold', "
                    "    f.properties.cancel_window_expires = $cancel_window_expires "
                    "RETURN f.id AS id"
                )
                try:
                    result = await store.execute_write(
                        tombstone_query,
                        {
                            "fact_id": fact_id,
                            "silo_id": silo_id,
                            "tombstoned_at": now.isoformat(),
                            "cancel_window_expires": cancel_window_expires.isoformat(),
                        },
                    )
                    if result:
                        facts_tombstoned += 1
                        log.info(
                            "chain_tombstoned_fact_tombstoned",
                            fact_id=fact_id,
                            remaining_chains=remaining_count,
                        )
                except Exception:
                    log.exception(
                        "chain_tombstoned_fact_tombstone_error",
                        fact_id=fact_id,
                    )

        elapsed_ms = (_time.perf_counter() - start_time) * 1000
        log.info(
            "chain_tombstoned_task_done",
            chain_id=chain_id,
            facts_evaluated=len(fact_rows),
            facts_staled=facts_staled,
            facts_tombstoned=facts_tombstoned,
            latency_ms=round(elapsed_ms, 2),
        )
