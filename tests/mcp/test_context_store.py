"""Tests for context_store tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_ORG_ID = "test-org"


def _make_node() -> MagicMock:
    node = MagicMock()
    node.id = uuid.uuid4()
    return node


@pytest.fixture
def mock_remember():
    node = _make_node()
    with patch(
        "context_service.mcp.tools.context_store._context_remember",
        new_callable=AsyncMock,
        return_value={"node_id": str(node.id), "layer": "memory", "decay_class": "standard", "created_at": "2026-01-01T00:00:00+00:00"},
    ) as m:
        yield m


@pytest.fixture
def mock_assert():
    node = _make_node()
    with patch(
        "context_service.mcp.tools.context_store._context_assert",
        new_callable=AsyncMock,
        return_value={
            "node_id": str(node.id),
            "layer": "knowledge",
            "claim_type": "freeform",
            "evidence_status": "verified",
            "evidence_nodes": [],
            "promoted_to_fact": False,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ) as m:
        yield m


@pytest.fixture
def mock_commit():
    node = _make_node()
    with patch(
        "context_service.mcp.tools.context_store._context_commit",
        new_callable=AsyncMock,
        return_value={
            "node_id": str(node.id),
            "layer": "wisdom",
            "declared_by": _ORG_ID,
            "about_nodes": ["node-1"],
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ) as m:
        yield m


@pytest.fixture
def mock_reason():
    with patch(
        "context_service.mcp.tools.context_store._context_reason",
        new_callable=AsyncMock,
        return_value={
            "chain_id": str(uuid.uuid4()),
            "layer": "intelligence",
            "steps_count": 1,
            "crystallizations_queued": 0,
            "session_id": str(uuid.uuid4()),
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ) as m:
        yield m


@pytest.fixture
def mock_reflect():
    node = _make_node()
    with patch(
        "context_service.mcp.tools.context_store._context_reflect",
        new_callable=AsyncMock,
        return_value={
            "node_id": str(node.id),
            "observation_type": "insight",
            "about_nodes": ["node-1"],
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_store_memory(mock_remember):
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(silo_id=_SILO_ID, content="Hello world", layer="memory")

    assert result["layer"] == "memory"
    assert "node_id" in result
    mock_remember.assert_called_once()


@pytest.mark.asyncio
async def test_store_knowledge(mock_assert):
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Tokens expire in 30 days",
        layer="knowledge",
        evidence=["node:abc-123"],
        source_type="document",
    )

    assert result["layer"] == "knowledge"
    mock_assert.assert_called_once()


@pytest.mark.asyncio
async def test_store_knowledge_missing_evidence():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Some claim",
        layer="knowledge",
        source_type="document",
    )

    assert result["error"] == "missing_evidence"


@pytest.mark.asyncio
async def test_store_knowledge_missing_source_type():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Some claim",
        layer="knowledge",
        evidence=["node:abc-123"],
    )

    assert result["error"] == "missing_source_type"


@pytest.mark.asyncio
async def test_store_wisdom(mock_commit):
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="We should prefer async patterns",
        layer="wisdom",
        about=["node-1"],
    )

    assert result["layer"] == "wisdom"
    mock_commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_wisdom_missing_about():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Some belief",
        layer="wisdom",
    )

    assert result["error"] == "missing_about"


@pytest.mark.asyncio
async def test_store_intelligence(mock_reason):
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Therefore X is true",
        layer="intelligence",
        steps=[{"step": "Observe A", "reasoning": "A implies B"}],
    )

    assert result["layer"] == "intelligence"
    mock_reason.assert_called_once()


@pytest.mark.asyncio
async def test_store_intelligence_missing_steps():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Conclusion",
        layer="intelligence",
    )

    assert result["error"] == "missing_steps"


@pytest.mark.asyncio
async def test_store_meta(mock_reflect):
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="My confidence shifted",
        layer="meta",
        observation_type="insight",
        about=["node-1"],
    )

    assert "layer" in result
    mock_reflect.assert_called_once()


@pytest.mark.asyncio
async def test_store_meta_missing_observation_type():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Something",
        layer="meta",
        about=["node-1"],
    )

    assert result["error"] == "missing_observation_type"


@pytest.mark.asyncio
async def test_store_meta_missing_about():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(
        silo_id=_SILO_ID,
        content="Something",
        layer="meta",
        observation_type="insight",
    )

    assert result["error"] == "missing_about"


@pytest.mark.asyncio
async def test_store_invalid_layer():
    from context_service.mcp.tools.context_store import _context_store

    result = await _context_store(silo_id=_SILO_ID, content="Something", layer="invalid")

    assert result["error"] == "invalid_layer"
