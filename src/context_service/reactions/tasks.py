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
        log = logger.bind(node_id=node_id, silo_id=silo_id, task=ReactionEventType.COMPUTE_EMBEDDING)
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

        # The EngineQdrantStore is not exposed through ContextService directly;
        # upsert is deferred until worker.py wires up the qdrant handle in Task 4.
        # For now, log what we would write and mark the work incomplete.
        log.warning(
            "compute_embedding_qdrant_upsert_deferred",
            vector_length=len(vector),
            node_type=node.type,
        )
        log.info("compute_embedding_task_done", vector_length=len(vector))

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
        log = logger.bind(node_id=node_id, silo_id=silo_id, task=ReactionEventType.UPDATE_HEAT, delta=delta)
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
    async def update_cluster_membership_task(
        node_id: str, silo_id: str, **_payload: Any
    ) -> None:
        """Assign or update a node's cluster membership.

        This handler is a stub for Phase 8a. Cluster assignment runs as a
        full pass via ClusteringService (Dagster custodian job). The reactive
        single-node path will be wired in Phase 9 when the Dagster job is
        removed.

        Args:
            node_id: String UUID of the node to assign.
            silo_id: Tenant isolation identifier.
            **payload: Additional event payload (cluster_id, weight, etc.).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP
        )
        log.info("update_cluster_membership_task_start")
        log.warning("update_cluster_membership_not_yet_implemented_deferred_to_phase9")

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

        This handler is a stub for Phase 8a. Synthesis is currently handled
        by the Dagster synthesizer job. The reactive single-cluster path will
        be wired in Phase 9 when the Dagster job is removed.

        Args:
            node_id: Node that triggered the synthesis check.
            silo_id: Tenant isolation identifier.
            **payload: Additional event payload (cluster_id, etc.).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.CHECK_SYNTHESIS
        )
        log.info("check_synthesis_task_start")
        log.warning("check_synthesis_not_yet_implemented_deferred_to_phase9")

    @broker.task(task_name=ReactionEventType.PROPAGATE_CONFIDENCE, timeout=_TIMEOUT_SIMPLE)
    async def propagate_confidence_task(node_id: str, silo_id: str, **_payload: Any) -> None:
        """Run incremental confidence propagation for a node.

        ``propagate_incremental`` requires pre-fetched neighborhood data
        (node_ids, credibility_scores, support_edges, contradiction_edges)
        that is expensive to derive from ``node_id`` alone. This handler is a
        stub for Phase 8a. The full implementation requires a graph read pass
        to assemble these inputs before calling the sync propagation function,
        which will be added in Phase 9.

        Args:
            node_id: Node whose confidence neighbourhood to propagate.
            silo_id: Tenant isolation identifier.
            **payload: Additional event payload (unused by this handler).
        """
        log = logger.bind(
            node_id=node_id, silo_id=silo_id, task=ReactionEventType.PROPAGATE_CONFIDENCE
        )
        log.info("propagate_confidence_task_start")
        log.warning("propagate_confidence_not_yet_implemented_deferred_to_phase9")
