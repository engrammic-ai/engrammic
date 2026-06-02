"""Shared fixtures for reactions tests."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from taskiq import InMemoryBroker

from context_service.reactions.broker import get_broker
from context_service.reactions.events import ReactionEvent, ReactionEventType
from context_service.reactions.tasks import register_tasks


@pytest.fixture(autouse=True)
def clear_broker_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_broker before and after each test.

    Prevents cached broker instances (possibly with stale configuration or
    side-effectful state) from leaking between tests.
    """
    get_broker.cache_clear()
    yield
    get_broker.cache_clear()


@pytest.fixture
def silo_id() -> str:
    return "test-silo-" + uuid.uuid4().hex[:8]


@pytest.fixture
def node_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def in_memory_broker() -> InMemoryBroker:
    """Return a fresh InMemoryBroker with all reaction tasks registered.

    ``await_inplace=True`` makes the broker execute tasks synchronously within
    the same event loop turn as ``kiq``, so patches applied in a ``with``
    block are still active when the task body runs.
    """
    broker = InMemoryBroker(await_inplace=True)
    register_tasks(broker)
    return broker


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    """AsyncMock that satisfies the HyperGraphStore interface used by tasks."""
    store = AsyncMock()
    store.get_node = AsyncMock(return_value=None)
    store.execute_write = AsyncMock(return_value=[])
    store.execute_query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_context_service(mock_graph_store: AsyncMock) -> MagicMock:
    """Minimal ContextService mock exposing graph_store."""
    ctx_svc = MagicMock()
    ctx_svc.graph_store = mock_graph_store
    return ctx_svc


@pytest.fixture
def sample_event(node_id: str, silo_id: str) -> ReactionEvent:
    return ReactionEvent(
        event_type=ReactionEventType.COMPUTE_EMBEDDING,
        node_id=node_id,
        silo_id=silo_id,
    )
