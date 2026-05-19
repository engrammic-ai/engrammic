"""Unit tests for knowledge-version bump on Knowledge-layer writes."""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context import ContextService
from context_service.services.models import ScopeContext


def _make_scope() -> ScopeContext:
    return ScopeContext(org_id="test-org", silo_id=uuid.uuid4())


def _make_service(with_cache: bool = True) -> tuple[ContextService, AsyncMock | None]:
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock(return_value=[])
    memgraph.execute_query = AsyncMock(return_value=[])

    qdrant = AsyncMock()
    qdrant.upsert = AsyncMock(return_value=None)

    embedding = AsyncMock()
    embedding.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])

    cache: AsyncMock | None = None
    if with_cache:
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(return_value=None)
        cache.set_nx = AsyncMock(return_value=True)
        cache.incr = AsyncMock(return_value=1)

    svc = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        cache=cache,
    )
    return svc, cache


_SETTINGS_PATCH = {
    "expansion_generation_enabled": False,
    "heat_ranking_enabled": False,
    "heat_weight": 0.0,
    "freshness_weight": 0.0,
    "freshness_sigma_days": 30,
}


@pytest.mark.asyncio
async def test_knowledge_write_bumps_version() -> None:
    """store() with a Fact node must call incr once with the silo knowledge_version key."""
    svc, cache = _make_service(with_cache=True)
    assert cache is not None
    scope = _make_scope()

    settings_mock = MagicMock(**_SETTINGS_PATCH)
    settings_mock.identities.custodian.enabled = False

    created_coros: list[object] = []

    with (
        patch("context_service.services.context.get_settings", return_value=settings_mock),
        patch(
            "context_service.services.context.asyncio.create_task",
            side_effect=lambda coro: created_coros.append(coro),
        ),
    ):
        await svc.store(
            scope=scope,
            content="Protein folding determines molecular function",
            node_type="Fact",
            properties={"confidence": 0.9},
        )

    # Drain collected coroutines so that incr is actually invoked.
    for coro in created_coros:
        if inspect.isawaitable(coro):
            await coro  # type: ignore[misc]

    expected_key = f"silo:{scope.silo_id}:knowledge_version"
    cache.incr.assert_called_once_with(expected_key)


@pytest.mark.asyncio
async def test_non_knowledge_write_does_not_bump_version() -> None:
    """store() with a Memory-layer node (Utterance) must NOT call incr on the cache."""
    svc, cache = _make_service(with_cache=True)
    assert cache is not None
    scope = _make_scope()

    settings_mock = MagicMock(**_SETTINGS_PATCH)
    settings_mock.identities.custodian.enabled = False

    with (
        patch("context_service.services.context.get_settings", return_value=settings_mock),
        patch("context_service.services.context.asyncio.create_task"),
    ):
        await svc.store(
            scope=scope,
            content="User opened the dashboard",
            node_type="Utterance",
        )

    cache.incr.assert_not_called()
