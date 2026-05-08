"""Protocol interface coverage tests for engine/protocols.py (B-001).

Verifies:
  1. HealthCheckable protocol -- method presence and signature.
  2. Closeable protocol -- method presence and signature.
  3. HyperGraphStore protocol -- runtime_checkable, complete method inventory
     including upsert_agent and upsert_reasoning_chain added after B-007.
  4. Protocol runtime checks -- FakeGraphStore satisfies isinstance() and
     MemgraphStore is a concrete class that declares HyperGraphStore methods.
"""

from __future__ import annotations

import inspect

import pytest

from context_service.engine.protocols import Closeable, HealthCheckable, HyperGraphStore
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# HealthCheckable protocol
# ---------------------------------------------------------------------------


class _ConcreteHealthCheckable:
    async def health_check(self) -> bool:
        return True


class _MissingHealthCheckable:
    """Does not implement health_check."""


def test_health_checkable_has_health_check_method() -> None:
    """HealthCheckable protocol requires an async health_check() method."""
    assert hasattr(HealthCheckable, "health_check")


def test_health_checkable_health_check_is_async() -> None:
    """health_check must be a coroutine function on a valid implementation."""
    assert inspect.iscoroutinefunction(_ConcreteHealthCheckable.health_check)


def test_health_checkable_health_check_returns_bool_annotation() -> None:
    """health_check return annotation on the protocol must annotate bool.

    Under ``from __future__ import annotations`` annotations are stored as
    strings at definition time, so we accept either the string 'bool' or the
    actual bool type to handle both evaluation modes.
    """
    sig = inspect.signature(HealthCheckable.health_check)
    annotation = sig.return_annotation
    assert annotation in (bool, "bool"), (
        f"health_check return annotation should be bool, got {annotation!r}"
    )


# ---------------------------------------------------------------------------
# Closeable protocol
# ---------------------------------------------------------------------------


class _ConcreteCloseable:
    async def close(self) -> None:
        pass


def test_closeable_has_close_method() -> None:
    """Closeable protocol requires a close() method."""
    assert hasattr(Closeable, "close")


def test_closeable_close_is_async() -> None:
    """close() must be a coroutine function on a valid implementation."""
    assert inspect.iscoroutinefunction(_ConcreteCloseable.close)


def test_closeable_close_takes_no_extra_args() -> None:
    """close() takes only self -- no extra required positional args beyond self."""
    sig = inspect.signature(Closeable.close)
    # On an unbound Protocol method, inspect retains 'self' in parameters.
    # We want exactly zero *additional* required positional params (excluding self).
    required_non_self = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is inspect.Parameter.empty
        and p.name != "self"
    ]
    assert len(required_non_self) == 0


# ---------------------------------------------------------------------------
# HyperGraphStore -- runtime_checkable
# ---------------------------------------------------------------------------


def test_hyper_graph_store_is_runtime_checkable() -> None:
    """HyperGraphStore must carry the @runtime_checkable decorator."""
    store = FakeGraphStore()
    # Would raise TypeError if not runtime_checkable
    result = isinstance(store, HyperGraphStore)
    assert isinstance(result, bool)


def test_fake_graph_store_satisfies_hyper_graph_store() -> None:
    """FakeGraphStore must pass isinstance() against HyperGraphStore."""
    assert isinstance(FakeGraphStore(), HyperGraphStore)


# ---------------------------------------------------------------------------
# HyperGraphStore -- complete method inventory (including post-B-007 additions)
# ---------------------------------------------------------------------------

# Format: (method_name, min_positional_args_excluding_self)
# Covers all 34 declared protocol methods.
_ALL_PROTOCOL_METHODS: list[tuple[str, int]] = [
    # Node CRUD
    ("upsert_node", 1),
    ("get_node", 2),
    ("batch_get_nodes", 2),
    ("delete_node", 2),
    ("create_supersedes_edge", 4),
    ("filter_superseded_at", 3),
    ("find_nodes", 1),
    ("count_nodes", 1),
    ("count_edges_in_silo", 1),
    ("sum_content_bytes_in_silo", 1),
    # Binary Edge CRUD
    ("upsert_binary_edge", 2),
    ("get_binary_edges", 2),
    ("get_entity_graph_neighbors", 2),
    ("delete_binary_edge", 2),
    # HyperEdge CRUD
    ("upsert_hyperedge", 2),
    ("get_hyperedge", 2),
    ("get_hyperedges_for_node", 2),
    ("delete_hyperedge", 2),
    # Graph traversal
    ("neighborhood", 2),
    ("shared_participation", 2),
    ("shortest_path", 3),
    # Silo CRUD
    ("create_silo", 1),
    ("get_silo", 1),
    ("list_silos", 1),
    ("update_silo", 1),
    ("delete_silo", 1),
    # Agent Identity (v1.5 phase 5a)
    ("upsert_agent", 2),
    # ReasoningChain Projection
    ("upsert_reasoning_chain", 12),
    # Bulk Operations
    ("batch_upsert_nodes", 1),
    ("batch_upsert_binary_edges", 2),
    # Schema
    ("ensure_indexes", 0),
    # Escape hatches
    ("execute_query", 1),
    ("execute_write", 1),
    ("session", 0),
    ("transaction", 0),
]


@pytest.mark.parametrize("method_name,min_args", _ALL_PROTOCOL_METHODS)
def test_hyper_graph_store_declares_method(method_name: str, min_args: int) -> None:
    """HyperGraphStore protocol must declare each method with the expected arity."""
    assert hasattr(HyperGraphStore, method_name), (
        f"HyperGraphStore is missing method: {method_name}"
    )
    method = getattr(HyperGraphStore, method_name)
    assert callable(method), f"HyperGraphStore.{method_name} is not callable"

    sig = inspect.signature(method)
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        # exclude 'self'
        and p.name != "self"
    ]
    assert len(positional) >= min_args, (
        f"HyperGraphStore.{method_name} has {len(positional)} positional param(s) "
        f"(excluding self), expected at least {min_args}"
    )


@pytest.mark.parametrize("method_name,min_args", _ALL_PROTOCOL_METHODS)
def test_fake_graph_store_method_satisfies_protocol(method_name: str, min_args: int) -> None:
    """FakeGraphStore must implement every protocol method with matching arity."""
    store = FakeGraphStore()
    assert hasattr(store, method_name), (
        f"FakeGraphStore is missing required protocol method: {method_name}"
    )
    method = getattr(store, method_name)
    assert callable(method), f"FakeGraphStore.{method_name} is not callable"

    sig = inspect.signature(method)
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert len(positional) >= min_args, (
        f"FakeGraphStore.{method_name} has {len(positional)} positional param(s), "
        f"expected at least {min_args}"
    )


# ---------------------------------------------------------------------------
# Async coroutine checks on FakeGraphStore implementations
# ---------------------------------------------------------------------------

_ASYNC_PROTOCOL_METHODS = [
    "upsert_node",
    "get_node",
    "batch_get_nodes",
    "delete_node",
    "create_supersedes_edge",
    "filter_superseded_at",
    "find_nodes",
    "count_nodes",
    "count_edges_in_silo",
    "sum_content_bytes_in_silo",
    "upsert_binary_edge",
    "get_binary_edges",
    "get_entity_graph_neighbors",
    "delete_binary_edge",
    "upsert_hyperedge",
    "get_hyperedge",
    "get_hyperedges_for_node",
    "delete_hyperedge",
    "neighborhood",
    "shared_participation",
    "shortest_path",
    "create_silo",
    "get_silo",
    "list_silos",
    "update_silo",
    "delete_silo",
    "upsert_agent",
    "upsert_reasoning_chain",
    "batch_upsert_nodes",
    "batch_upsert_binary_edges",
    "ensure_indexes",
    "execute_query",
    "execute_write",
]


@pytest.mark.parametrize("method_name", _ASYNC_PROTOCOL_METHODS)
def test_fake_graph_store_async_methods_are_coroutines(method_name: str) -> None:
    """All protocol async methods must be coroutine functions on FakeGraphStore."""
    method = getattr(FakeGraphStore, method_name)
    assert inspect.iscoroutinefunction(method), (
        f"FakeGraphStore.{method_name} should be async but is not a coroutine function"
    )


# ---------------------------------------------------------------------------
# Context manager escape hatches
# ---------------------------------------------------------------------------


def test_fake_graph_store_session_returns_async_context_manager() -> None:
    """session() must return an object with __aenter__ and __aexit__."""
    store = FakeGraphStore()
    cm = store.session()
    assert cm is not None
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")


def test_fake_graph_store_transaction_returns_async_context_manager() -> None:
    """transaction() must return an object with __aenter__ and __aexit__."""
    store = FakeGraphStore()
    cm = store.transaction()
    assert cm is not None
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")


# ---------------------------------------------------------------------------
# MemgraphStore class-level protocol compliance
# ---------------------------------------------------------------------------


def test_memgraph_store_is_a_class() -> None:
    """MemgraphStore must be importable and be a class."""
    from context_service.engine.memgraph_store import MemgraphStore

    assert isinstance(MemgraphStore, type)


def test_memgraph_store_declares_hyper_graph_store_methods() -> None:
    """MemgraphStore must declare all HyperGraphStore node-CRUD methods."""
    from context_service.engine.memgraph_store import MemgraphStore

    core_methods = [
        "upsert_node",
        "get_node",
        "batch_get_nodes",
        "delete_node",
        "upsert_binary_edge",
        "upsert_hyperedge",
        "neighborhood",
        "create_silo",
        "get_silo",
        "upsert_agent",
        "upsert_reasoning_chain",
        "execute_query",
        "execute_write",
        "session",
        "transaction",
    ]
    missing = [m for m in core_methods if not hasattr(MemgraphStore, m)]
    assert missing == [], f"MemgraphStore is missing methods: {missing}"
