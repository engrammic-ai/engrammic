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
        return_value={
            "node_id": str(node.id),
            "layer": "memory",
            "decay_class": "standard",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
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


@pytest.mark.asyncio
async def test_store_memory_routes_to_remember(mock_remember):
    from context_service.mcp.tools.context_store import _context_store

    await _context_store(silo_id=_SILO_ID, content="test memory", layer="memory")

    mock_remember.assert_called_once()
    call_kwargs = mock_remember.call_args.kwargs
    assert call_kwargs["content"] == "test memory"
    assert call_kwargs["silo_id"] == _SILO_ID


@pytest.mark.asyncio
async def test_store_knowledge_routes_to_assert(mock_assert):
    from context_service.mcp.tools.context_store import _context_store

    await _context_store(
        silo_id=_SILO_ID,
        content="test knowledge",
        layer="knowledge",
        evidence=["node:abc-123"],
        source_type="document",
    )

    mock_assert.assert_called_once()
    call_kwargs = mock_assert.call_args.kwargs
    assert call_kwargs["claim"] == "test knowledge"
    assert call_kwargs["silo_id"] == _SILO_ID


@pytest.mark.asyncio
async def test_store_wisdom_routes_to_commit(mock_commit):
    from context_service.mcp.tools.context_store import _context_store

    await _context_store(
        silo_id=_SILO_ID,
        content="test wisdom",
        layer="wisdom",
        about=["node-1"],
    )

    mock_commit.assert_called_once()
    call_kwargs = mock_commit.call_args.kwargs
    assert call_kwargs["belief"] == "test wisdom"
    assert call_kwargs["silo_id"] == _SILO_ID


@pytest.mark.asyncio
async def test_store_intelligence_routes_to_reason(mock_reason):
    from context_service.mcp.tools.context_store import _context_store

    await _context_store(
        silo_id=_SILO_ID,
        content="test reasoning",
        layer="intelligence",
        steps=[{"step": "Observe A", "reasoning": "A implies B"}],
    )

    mock_reason.assert_called_once()
    call_kwargs = mock_reason.call_args.kwargs
    assert call_kwargs["conclusion"] == "test reasoning"
    assert call_kwargs["silo_id"] == _SILO_ID


@pytest.mark.asyncio
async def test_store_meta_routes_to_reflect(mock_reflect):
    from context_service.mcp.tools.context_store import _context_store

    await _context_store(
        silo_id=_SILO_ID,
        content="test reflection",
        layer="meta",
        observation_type="insight",
        about=["node-1"],
    )

    mock_reflect.assert_called_once()
    call_kwargs = mock_reflect.call_args.kwargs
    assert call_kwargs["observation"] == "test reflection"
    assert call_kwargs["silo_id"] == _SILO_ID


@pytest.fixture
def mock_reason_deps():
    """Mock all dependencies for direct _context_reason tests."""
    from context_service.auth.context import AuthContext

    auth = AuthContext(
        org_id=_ORG_ID,
        user_id="user-1",
        email="user@test.com",
        is_dev=True,
        agent_id=None,
        session_id=None,
    )

    ctx_svc = MagicMock()

    graph_store = AsyncMock()
    graph_store.execute_query = AsyncMock(return_value=[])
    ctx_svc.graph_store = graph_store

    postgres_store = AsyncMock()
    postgres_store.upsert_chain_steps = AsyncMock(return_value=None)
    postgres_store.upsert_reasoning_chain = AsyncMock(return_value=None)

    with (
        patch(
            "context_service.mcp.tools.context_store.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=auth,
        ),
        patch(
            "context_service.mcp.tools.context_store.get_context_service",
            return_value=ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_store.get_postgres_store",
            return_value=postgres_store,
        ),
        patch(
            "context_service.mcp.tools.context_store.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_store.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.engine.chain_saga.ChainSagaWriter.write_chain",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.engine.sessions.create_or_join_session",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.engine.sessions.attach_chain_to_session",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        yield {"auth": auth, "ctx_svc": ctx_svc, "postgres_store": postgres_store}


@pytest.mark.asyncio
async def test_context_reason_attaches_query_embedding(mock_reason_deps):
    """_context_reason calls embed and upserts query embedding on chain creation."""
    from context_service.mcp.tools.context_store import _context_reason

    with (
        patch(
            "context_service.mcp.tools.context_store.embed",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ) as mock_embed,
        patch(
            "context_service.mcp.tools.context_store._upsert_chain_embedding",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_upsert,
    ):
        result = await _context_reason(
            silo_id=_SILO_ID,
            steps=[{"step": 1, "reasoning": "A implies B"}],
            conclusion="Therefore B is true",
        )

        assert "error" not in result
        assert result["layer"] == "intelligence"
        mock_embed.assert_called_once_with("Therefore B is true")
        mock_upsert.assert_called_once()
        upsert_kwargs = mock_upsert.call_args
        assert upsert_kwargs[0][1] == _SILO_ID
        assert upsert_kwargs[0][2] == [0.1] * 768


@pytest.mark.asyncio
async def test_context_reason_skips_embedding_when_no_conclusion(mock_reason_deps):
    """_context_reason does not call embed when conclusion is None."""
    from context_service.mcp.tools.context_store import _context_reason

    with (
        patch(
            "context_service.mcp.tools.context_store.embed",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ) as mock_embed,
        patch(
            "context_service.mcp.tools.context_store._upsert_chain_embedding",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await _context_reason(
            silo_id=_SILO_ID,
            steps=[{"step": 1, "reasoning": "A implies B"}],
            conclusion=None,
        )

        assert "error" not in result
        mock_embed.assert_not_called()
