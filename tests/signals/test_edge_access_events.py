from unittest.mock import AsyncMock

import pytest

from context_service.signals.edge_access_events import (
    edge_access_stream_key,
    edge_id,
    emit_edge_access_event,
)


def test_edge_access_stream_key():
    assert edge_access_stream_key("silo-123") == "silo:silo-123:edge_access_events"


def test_edge_id_deterministic():
    eid1 = edge_id("node-a", "node-b", "RELATED_TO")
    eid2 = edge_id("node-b", "node-a", "RELATED_TO")
    assert eid1 == eid2


def test_edge_id_different_types():
    eid1 = edge_id("node-a", "node-b", "RELATED_TO")
    eid2 = edge_id("node-a", "node-b", "DERIVES_FROM")
    assert eid1 != eid2


@pytest.mark.asyncio
async def test_emit_edge_access_event_success():
    redis = AsyncMock()
    redis.xadd = AsyncMock()

    await emit_edge_access_event(
        redis=redis,
        silo_id="silo-123",
        from_node="node-a",
        to_node="node-b",
        edge_type="RELATED_TO",
    )

    redis.xadd.assert_called_once()
    call_args = redis.xadd.call_args
    assert call_args[0][0] == "silo:silo-123:edge_access_events"


@pytest.mark.asyncio
async def test_emit_edge_access_event_swallows_errors():
    redis = AsyncMock()
    redis.xadd = AsyncMock(side_effect=Exception("Redis down"))

    # Should not raise
    await emit_edge_access_event(
        redis=redis,
        silo_id="silo-123",
        from_node="node-a",
        to_node="node-b",
        edge_type="RELATED_TO",
    )
