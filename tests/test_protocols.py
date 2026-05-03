"""Protocol conformance tests for engine/protocols.py (B-007).

Verifies that:
  1. HyperGraphStore is importable and runtime_checkable.
  2. FakeGraphStore satisfies isinstance() against HyperGraphStore.
  3. All required protocol methods exist on FakeGraphStore with the correct
     arity (argument count), covering both implemented and stub methods.
"""

from __future__ import annotations

import inspect

import pytest

from context_service.engine.protocols import HyperGraphStore
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# isinstance() / runtime_checkable conformance
# ---------------------------------------------------------------------------


def test_fake_graph_store_is_instance_of_hyper_graph_store() -> None:
    """FakeGraphStore must satisfy the runtime_checkable HyperGraphStore protocol."""
    store = FakeGraphStore()
    assert isinstance(store, HyperGraphStore)


# ---------------------------------------------------------------------------
# Method presence and arity
# ---------------------------------------------------------------------------

# Each entry is (method_name, minimum_positional_args_excluding_self).
# We check >= so that default-argument additions don't break the test.
_REQUIRED_METHODS: list[tuple[str, int]] = [
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
    # Bulk operations
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


@pytest.mark.parametrize("method_name,min_args", _REQUIRED_METHODS)
def test_fake_graph_store_has_method(method_name: str, min_args: int) -> None:
    """Each protocol method must exist on FakeGraphStore with at least min_args positional params."""
    store = FakeGraphStore()
    assert hasattr(store, method_name), (
        f"FakeGraphStore is missing required protocol method: {method_name}"
    )
    method = getattr(store, method_name)
    assert callable(method), f"FakeGraphStore.{method_name} is not callable"

    sig = inspect.signature(method)
    # Count parameters that can be passed positionally (exclude **kwargs, *args name itself,
    # and keyword-only params that follow a bare *).
    positional_params = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    assert len(positional_params) >= min_args, (
        f"FakeGraphStore.{method_name} has {len(positional_params)} positional param(s), "
        f"expected at least {min_args}"
    )


# ---------------------------------------------------------------------------
# Async coroutine check for async methods
# ---------------------------------------------------------------------------

_ASYNC_METHODS = [
    "upsert_node",
    "get_node",
    "execute_query",
    "execute_write",
    "ensure_indexes",
    "create_silo",
    "get_silo",
]


@pytest.mark.parametrize("method_name", _ASYNC_METHODS)
def test_fake_graph_store_async_methods_are_coroutines(method_name: str) -> None:
    """Key async methods must be coroutine functions (not plain sync callables)."""
    method = getattr(FakeGraphStore, method_name)
    assert inspect.iscoroutinefunction(method), (
        f"FakeGraphStore.{method_name} should be async but is not a coroutine function"
    )


# ---------------------------------------------------------------------------
# Context manager methods return something (non-None)
# ---------------------------------------------------------------------------


def test_session_returns_context_manager() -> None:
    """session() must return an object (async context manager)."""
    store = FakeGraphStore()
    cm = store.session()
    assert cm is not None
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__"), (
        "session() must return an async context manager"
    )


def test_transaction_returns_context_manager() -> None:
    """transaction() must return an object (async context manager)."""
    store = FakeGraphStore()
    cm = store.transaction()
    assert cm is not None
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__"), (
        "transaction() must return an async context manager"
    )
