"""Storage protocol for the hypergraph engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from context_service.engine.raw_cypher import RawCypherMixin

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from context_service.engine.models import BinaryEdge, HyperEdge, Node, Silo, SubGraph
    from context_service.services.models import ScopeContext


class HealthCheckable(Protocol):
    """Protocol for backing stores that can report liveness."""

    async def health_check(self) -> bool: ...


class Closeable(Protocol):
    """Protocol for resources that need explicit cleanup."""

    async def close(self) -> None: ...


@runtime_checkable
class HyperGraphStore(RawCypherMixin, Protocol):
    """Domain-agnostic graph storage interface.

    All methods that return lists use cursor-based pagination.
    All read/write methods scoped to Nodes/Edges use silo_id for isolation.
    Silo CRUD methods use org_id (WorkOS org owner).
    upsert_node performs version checks for optimistic concurrency.
    """

    # --- Node CRUD ---

    async def upsert_node(self, node: Node) -> None:
        """Create or update a node. Raises StaleVersionError on version mismatch."""
        ...

    async def get_node(self, node_id: uuid.UUID, silo_id: str) -> Node | None: ...

    async def batch_get_nodes(
        self, node_ids: list[uuid.UUID], silo_id: str
    ) -> dict[uuid.UUID, Node]: ...

    async def delete_node(self, node_id: uuid.UUID, silo_id: str) -> bool: ...

    async def create_supersedes_edge(
        self,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
        silo_id: str,
        valid_from: datetime,
        source: str = "custodian",
        reason: str = "contradiction",
    ) -> bool:
        """Link a newer node to an older one with a :SUPERSEDES edge.

        Used by the Custodian to record semantic supersession between
        independently-stored nodes (different doc_ids, no version chain).
        ``from_id`` supersedes ``to_id``. Sets ``to.valid_to`` = ``valid_from``
        if not already set. ``reason`` must be one of: contradiction,
        evidence_shift, author_update, evidence_erased (I5).
        """
        ...

    async def filter_superseded_at(
        self,
        node_ids: list[uuid.UUID],
        silo_id: str,
        as_of: datetime,
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Batch version-check: map each input id to its valid version at ``as_of``.

        Used by ``lookup(..., as_of=...)`` to substitute superseded ids
        with their current tips. Missing keys in the result indicate no
        valid version exists at that timestamp.
        """
        ...

    async def find_nodes(
        self,
        silo_id: str,
        *,
        type: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[Node], str | None]: ...

    async def count_nodes(self, silo_id: str) -> int: ...

    async def count_edges_in_silo(self, silo_id: str) -> int: ...

    async def sum_content_bytes_in_silo(self, silo_id: str) -> int: ...

    # --- Binary Edge CRUD ---

    async def upsert_binary_edge(self, edge: BinaryEdge, silo_id: str) -> None: ...

    async def get_binary_edges(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        type: str | None = None,
        direction: Literal["outgoing", "incoming", "both"] = "both",
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[BinaryEdge], str | None]: ...

    async def get_entity_graph_neighbors(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        limit: int = 50,
    ) -> list[tuple[Node, int]]:
        """Find neighbor Nodes reachable via the LLM-extracted entity graph.

        Returns a list of (neighbor_node, strength) tuples where strength is
        the count of distinct semantic relationships bridging the source
        and neighbor through their extracted entities. Used by GraphWalker
        to traverse the real knowledge graph on extraction-produced data,
        where direct (:Node)-[:EDGE]->(:Node) binary edges do not exist.
        """
        ...

    async def delete_binary_edge(self, edge_id: uuid.UUID, silo_id: str) -> bool: ...

    # --- HyperEdge CRUD ---

    async def upsert_hyperedge(self, edge: HyperEdge, silo_id: str) -> None: ...

    async def get_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> HyperEdge | None: ...

    async def get_hyperedges_for_node(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        type: str | None = None,
        role: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[HyperEdge], str | None]: ...

    async def delete_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> bool: ...

    # --- Graph Traversal ---

    async def neighborhood(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 100,
        silo_scope: list[str] | None = None,
    ) -> SubGraph: ...

    async def shared_participation(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        threshold: int = 2,
        limit: int = 50,
    ) -> list[tuple[Node, int]]: ...

    async def shortest_path(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 5,
    ) -> list[Node] | None: ...

    # --- Silo CRUD ---

    async def create_silo(self, silo: Silo) -> None: ...
    async def get_silo(self, scope: ScopeContext) -> Silo | None: ...
    async def list_silos(self, org_id: str) -> list[Silo]: ...
    async def update_silo(self, silo: Silo) -> None: ...
    async def delete_silo(self, scope: ScopeContext) -> bool: ...

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
        SPAWNED_BY edge. Lineage depth is capped at 3 hops by the underlying query.

        Returns the agent_id (unchanged) on success.
        Raises ValueError if parent_agent_id is not None but does not exist in silo.
        """
        ...

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
        """Upsert a :ReasoningChain summary projection to Memgraph.

        Called by ChainSagaWriter after the full steps have been persisted to
        Postgres. Writes only the summary fields needed for graph traversal and
        custodian scoring; full steps remain in Postgres.
        """
        ...

    # --- Bulk Operations ---

    async def batch_upsert_nodes(self, nodes: list[Node]) -> None: ...
    async def batch_upsert_binary_edges(self, edges: list[BinaryEdge], silo_id: str) -> None: ...

    # --- Schema ---

    async def ensure_indexes(self) -> None: ...

