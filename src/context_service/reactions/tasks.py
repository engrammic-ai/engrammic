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
from typing import TYPE_CHECKING, Any

import structlog
from taskiq_redis import ListQueueBroker

from context_service.reactions.events import ReactionEventType

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Taskiq timeout labels (seconds) - passed as task labels for middleware
_TIMEOUT_EMBEDDING = 30
_TIMEOUT_LLM = 300
_TIMEOUT_SIMPLE = 10
_TIMEOUT_CASCADE = 60

# Confidence propagation threshold - only write back if delta exceeds this
_CONFIDENCE_DELTA_THRESHOLD = 0.1


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
    async def batch_compute_embedding_task(
        items: list[dict], **_payload: Any
    ) -> None:
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
        vectors = await embedder.embed_batch(texts)

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
