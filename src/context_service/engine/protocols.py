"""Storage protocol for the hypergraph engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    import uuid
    from contextlib import AbstractAsyncContextManager
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
class HyperGraphStore(Protocol):
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

    async def get_epistemic_edges_for_nodes(
        self,
        node_ids: list[str],
        silo_id: str,
    ) -> dict[str, dict[str, list[str]]]:
        """Fetch epistemic edges (SUPPORTS, DERIVED_FROM, CONTRADICTS) for nodes.

        Returns a dict keyed by node_id, each containing:
          - supports: list of node IDs that support this node
          - derived_from: list of node IDs this node was derived from
          - contradicts: list of node IDs this node contradicts or is contradicted by
        """
        ...

    async def resolve_current_head(
        self,
        node_id: uuid.UUID,
        silo_id: str,
    ) -> uuid.UUID | None:
        """Resolve the current chain head for a node using O(1) pointer lookup.

        Returns the head node's id, or the input id if it's standalone/head.
        Returns None if node doesn't exist.
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

    # --- Chain Pruning ---

    async def find_stale_chain_interior(
        self,
        silo_id: str,
        max_length: int,
        batch_size: int = 100,
    ) -> list[str]:
        """Find interior chain nodes beyond max_length hops from the chain head."""
        ...

    async def convert_to_stub(self, node_id: str, silo_id: str) -> bool:
        """Convert a node to a stub by clearing content fields while preserving edges."""
        ...

    # --- Batch Dedup ---

    async def query_document_ids(self, silo_id: str, document_ids: list[str]) -> dict[str, str]:
        """Return {document_id: node_id} for nodes whose document_id is in the input list."""
        ...

    async def query_spo_pairs(
        self, silo_id: str, sp_pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Return existing nodes grouped by (subject, predicate) for supersession detection."""
        ...

    # --- Bulk Operations ---

    async def batch_upsert_nodes(self, nodes: list[Node]) -> None: ...
    async def batch_upsert_binary_edges(self, edges: list[BinaryEdge], silo_id: str) -> None: ...

    # --- Schema ---

    async def ensure_indexes(self) -> None: ...

    # --- Raw Cypher escape hatches ---
    # These methods exist to enable incremental migration of code that currently
    # bypasses the protocol and calls MemgraphClient directly. New code should
    # prefer the domain-level methods above wherever possible.

    async def execute_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a read-only Cypher query and return results as a list of dicts."""
        ...

    async def execute_write(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a write Cypher query within a transaction and return results as a list of dicts."""
        ...

    def session(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding a database session for transaction scope."""
        ...

    def transaction(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding an explicit transaction.

        The transaction is committed on clean exit and rolled back if the body raises.
        Prefer this over session() + begin_transaction() for atomic writes.
        """
        ...


@runtime_checkable
class EpistemicStore(Protocol):
    """CITE-domain operations for Wisdom/Intelligence layers.

    Sits above HyperGraphStore. Encapsulates belief synthesis,
    fact clustering, and reasoning chain operations.
    """

    async def get_fact_cluster(self, silo_id: str, cluster_id: str) -> list[dict[str, Any]]:
        """Get all facts in a cluster."""
        ...

    async def get_unclustered_facts(self, silo_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get facts not yet assigned to any cluster."""
        ...

    async def create_belief_with_links(
        self,
        silo_id: str,
        content: str,
        fact_ids: list[str],
        confidence: float,
        reasoning: str | None = None,
    ) -> str:
        """Atomically create a belief and link it to source facts."""
        ...

    async def update_belief_centroid(
        self,
        silo_id: str,
        belief_id: str,
        embedding_client: Any | None = None,
    ) -> None:
        """Update belief's centroid embedding. No-op if embedding_client is None."""
        ...

    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]:
        """Find beliefs similar to the given content."""
        ...

    async def check_belief_coverage(self, silo_id: str, fact_ids: list[str]) -> dict[str, Any]:
        """Check which facts are covered by existing beliefs."""
        ...

    async def merge_beliefs(
        self,
        silo_id: str,
        source_belief_ids: list[str],
        merged_content: str,
        fact_ids: list[str],
    ) -> str:
        """Atomically merge beliefs: create merged, link facts, mark sources stale."""
        ...

    async def mark_belief_stale(self, silo_id: str, belief_id: str, reason: str) -> None:
        """Mark a belief as stale with a reason."""
        ...
