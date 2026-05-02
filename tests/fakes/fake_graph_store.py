"""In-memory dict-backed fake implementation of HyperGraphStore.

Implements only the escape-hatch methods that existing unit tests exercise:
  - execute_query
  - execute_write
  - session

All other protocol methods raise NotImplementedError so tests fail fast if
they accidentally hit an unimplemented path.

Usage example::

    from tests.fakes.fake_graph_store import FakeGraphStore

    store = FakeGraphStore()
    # pre-seed rows that execute_query will return
    store.seed_query_result([{"h": 0.85}])

    result = await store.execute_query("MATCH ...", {})
    assert result == [{"h": 0.85}]
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncGenerator
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from typing import Literal

    from context_service.engine.models import BinaryEdge, HyperEdge, Node, Silo, SubGraph
    from context_service.services.models import ScopeContext


class _FakeSession:
    """Minimal async session yielded by FakeGraphStore.session()."""

    def __init__(self, store: FakeGraphStore) -> None:
        self._store = store

    async def run(
        self, statement: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self._store._write_log.append((statement, parameters or {}))
        return self._store._next_write_results.pop(0) if self._store._next_write_results else []


class FakeGraphStore:
    """Dict-backed in-memory HyperGraphStore for unit tests.

    Tests control responses by calling the seed helpers before the code under
    test runs:
      - seed_query_result(rows)  -- queued answer for the next execute_query call
      - seed_write_result(rows)  -- queued answer for the next execute_write call

    Recorded calls are available on:
      - query_log  -- list of (cypher, params) for each execute_query call
      - write_log  -- list of (cypher, params) for each execute_write call
    """

    def __init__(self) -> None:
        # Queued responses (FIFO per method).
        self._next_query_results: list[list[dict[str, Any]]] = []
        self._next_write_results: list[list[dict[str, Any]]] = []

        # Call logs for assertions.
        self._query_log: list[tuple[str, dict[str, Any]]] = []
        self._write_log: list[tuple[str, dict[str, Any]]] = []

    # --- Seed helpers ---

    def seed_query_result(self, rows: list[dict[str, Any]]) -> None:
        """Queue rows to be returned by the next execute_query call."""
        self._next_query_results.append(rows)

    def seed_write_result(self, rows: list[dict[str, Any]]) -> None:
        """Queue rows to be returned by the next execute_write call."""
        self._next_write_results.append(rows)

    # --- Inspection helpers ---

    @property
    def query_log(self) -> list[tuple[str, dict[str, Any]]]:
        return self._query_log

    @property
    def write_log(self) -> list[tuple[str, dict[str, Any]]]:
        return self._write_log

    # --- Escape-hatch methods (implemented) ---

    async def execute_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._query_log.append((cypher, params or {}))
        if self._next_query_results:
            return self._next_query_results.pop(0)
        return []

    async def execute_write(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._write_log.append((cypher, params or {}))
        if self._next_write_results:
            return self._next_write_results.pop(0)
        return []

    def session(self) -> AbstractAsyncContextManager[_FakeSession]:
        @asynccontextmanager
        async def _ctx() -> AsyncGenerator[_FakeSession, None]:
            yield _FakeSession(self)

        return _ctx()

    def transaction(self) -> AbstractAsyncContextManager[_FakeSession]:
        """Fake transaction context - same as session for test purposes."""
        return self.session()

    # --- Unimplemented protocol stubs ---
    # Raise NotImplementedError so tests fail clearly if they hit these.

    async def upsert_node(self, node: Node) -> None:
        raise NotImplementedError("FakeGraphStore.upsert_node not implemented")

    async def get_node(self, node_id: uuid.UUID, silo_id: str) -> Node | None:
        raise NotImplementedError("FakeGraphStore.get_node not implemented")

    async def batch_get_nodes(
        self, node_ids: list[uuid.UUID], silo_id: str
    ) -> dict[uuid.UUID, Node]:
        raise NotImplementedError("FakeGraphStore.batch_get_nodes not implemented")

    async def delete_node(self, node_id: uuid.UUID, silo_id: str) -> bool:
        raise NotImplementedError("FakeGraphStore.delete_node not implemented")

    async def create_supersedes_edge(
        self,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
        silo_id: str,
        valid_from: datetime,
        source: str = "custodian",
        reason: str = "contradiction",
    ) -> bool:
        raise NotImplementedError("FakeGraphStore.create_supersedes_edge not implemented")

    async def filter_superseded_at(
        self,
        node_ids: list[uuid.UUID],
        silo_id: str,
        as_of: datetime,
    ) -> dict[uuid.UUID, uuid.UUID]:
        raise NotImplementedError("FakeGraphStore.filter_superseded_at not implemented")

    async def find_nodes(
        self,
        silo_id: uuid.UUID,
        *,
        type: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[Node], str | None]:
        raise NotImplementedError("FakeGraphStore.find_nodes not implemented")

    async def count_nodes(self, silo_id: uuid.UUID) -> int:
        raise NotImplementedError("FakeGraphStore.count_nodes not implemented")

    async def count_edges_in_silo(self, silo_id: uuid.UUID) -> int:
        raise NotImplementedError("FakeGraphStore.count_edges_in_silo not implemented")

    async def sum_content_bytes_in_silo(self, silo_id: uuid.UUID) -> int:
        raise NotImplementedError("FakeGraphStore.sum_content_bytes_in_silo not implemented")

    async def upsert_binary_edge(self, edge: BinaryEdge, silo_id: str) -> None:
        raise NotImplementedError("FakeGraphStore.upsert_binary_edge not implemented")

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
        raise NotImplementedError("FakeGraphStore.get_binary_edges not implemented")

    async def get_entity_graph_neighbors(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        limit: int = 50,
    ) -> list[tuple[Node, int]]:
        raise NotImplementedError("FakeGraphStore.get_entity_graph_neighbors not implemented")

    async def delete_binary_edge(self, edge_id: uuid.UUID, silo_id: str) -> bool:
        raise NotImplementedError("FakeGraphStore.delete_binary_edge not implemented")

    async def upsert_hyperedge(self, edge: HyperEdge, silo_id: str) -> None:
        raise NotImplementedError("FakeGraphStore.upsert_hyperedge not implemented")

    async def get_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> HyperEdge | None:
        raise NotImplementedError("FakeGraphStore.get_hyperedge not implemented")

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
        raise NotImplementedError("FakeGraphStore.get_hyperedges_for_node not implemented")

    async def delete_hyperedge(self, edge_id: uuid.UUID, silo_id: str) -> bool:
        raise NotImplementedError("FakeGraphStore.delete_hyperedge not implemented")

    async def neighborhood(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 100,
        silo_scope: list[uuid.UUID] | None = None,
    ) -> SubGraph:
        raise NotImplementedError("FakeGraphStore.neighborhood not implemented")

    async def shared_participation(
        self,
        node_id: uuid.UUID,
        silo_id: str,
        *,
        threshold: int = 2,
        limit: int = 50,
    ) -> list[tuple[Node, int]]:
        raise NotImplementedError("FakeGraphStore.shared_participation not implemented")

    async def shortest_path(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        silo_id: str,
        *,
        max_depth: int = 5,
    ) -> list[Node] | None:
        raise NotImplementedError("FakeGraphStore.shortest_path not implemented")

    async def create_silo(self, silo: Silo) -> None:
        raise NotImplementedError("FakeGraphStore.create_silo not implemented")

    async def get_silo(self, scope: ScopeContext) -> Silo | None:
        raise NotImplementedError("FakeGraphStore.get_silo not implemented")

    async def list_silos(self, org_id: str) -> list[Silo]:
        raise NotImplementedError("FakeGraphStore.list_silos not implemented")

    async def update_silo(self, silo: Silo) -> None:
        raise NotImplementedError("FakeGraphStore.update_silo not implemented")

    async def delete_silo(self, scope: ScopeContext) -> bool:
        raise NotImplementedError("FakeGraphStore.delete_silo not implemented")

    async def batch_upsert_nodes(self, nodes: list[Node]) -> None:
        raise NotImplementedError("FakeGraphStore.batch_upsert_nodes not implemented")

    async def batch_upsert_binary_edges(self, edges: list[BinaryEdge], silo_id: str) -> None:
        raise NotImplementedError("FakeGraphStore.batch_upsert_binary_edges not implemented")

    async def ensure_indexes(self) -> None:
        raise NotImplementedError("FakeGraphStore.ensure_indexes not implemented")

    async def health_check(self) -> bool:
        raise NotImplementedError("FakeGraphStore.health_check not implemented")
