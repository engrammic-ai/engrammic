"""Unit tests for mcp/tools/context_get.py (B-010)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_ORG_ID = "test-org"


def _make_node(
    node_id: uuid.UUID | None = None,
    silo_id: uuid.UUID | None = None,
    content: str = "Test content",
    node_type: str = "Memory",
    properties: dict | None = None,
) -> MagicMock:
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.silo_id = silo_id or uuid.UUID(_SILO_ID)
    node.content = content
    node.type = node_type
    node.properties = properties if properties is not None else {}
    node.source_uri = None
    node.content_hash = None
    node.created_at = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
    return node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_auth():
    with patch(
        "context_service.mcp.tools.context_get.get_mcp_auth_context",
        new_callable=AsyncMock,
    ) as m:
        auth = MagicMock()
        auth.org_id = _ORG_ID
        m.return_value = auth
        yield auth


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.tools.context_get.get_context_service") as m:
        svc = AsyncMock()
        svc.get.return_value = None
        m.return_value = svc
        yield svc


@pytest.fixture
def mock_silo_valid():
    with (
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
    ):
        yield


@pytest.fixture
def mock_redis_none():
    with patch("context_service.mcp.tools.context_get.get_redis", return_value=None):
        yield


@pytest.fixture
def mock_metrics():
    with patch("context_service.mcp.tools.context_get.CONTEXT_GET_LATENCY") as m:
        yield m


# ---------------------------------------------------------------------------
# Tests: as_of guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as_of_returns_not_supported():
    from context_service.mcp.tools.context_get import _context_get

    result = await _context_get(node_ids=str(uuid.uuid4()), as_of="2026-01-01T00:00:00Z")

    assert result["error"] == "as_of_not_supported"
    assert "message" in result


# ---------------------------------------------------------------------------
# Tests: success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_single_node_success(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    node_id = uuid.uuid4()
    node = _make_node(node_id=node_id, properties={"layer": "memory", "confidence": 0.9})
    mock_context_service.get.return_value = node

    result = await _context_get(
        node_ids=str(node_id),
        silo_id=_SILO_ID,
    )

    assert "nodes" in result
    assert len(result["nodes"]) == 1
    entry = result["nodes"][0]
    assert entry["node_id"] == str(node_id)
    assert entry["content"] == node.content
    assert entry["type"] == node.type
    assert entry["layer"] == "memory"
    assert entry["confidence"] == 0.9
    assert entry["created_at"] == "2026-04-27T12:00:00+00:00"
    mock_context_service.get.assert_called_once_with(node_id, uuid.UUID(_SILO_ID))


@pytest.mark.asyncio
async def test_get_multiple_nodes_success(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    node_a = _make_node(node_id=id_a, content="Alpha")
    node_b = _make_node(node_id=id_b, content="Beta")
    mock_context_service.get.side_effect = [node_a, node_b]

    result = await _context_get(
        node_ids=[str(id_a), str(id_b)],
        silo_id=_SILO_ID,
    )

    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["content"] == "Alpha"
    assert result["nodes"][1]["content"] == "Beta"


@pytest.mark.asyncio
async def test_get_derives_silo_from_org_when_not_provided(
    mock_auth, mock_context_service, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    node_id = uuid.uuid4()
    mock_context_service.get.return_value = _make_node(node_id=node_id)

    result = await _context_get(node_ids=str(node_id))

    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["node_id"] == str(node_id)


# ---------------------------------------------------------------------------
# Tests: not-found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_not_found(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    node_id = uuid.uuid4()
    mock_context_service.get.return_value = None

    result = await _context_get(node_ids=str(node_id), silo_id=_SILO_ID)

    assert len(result["nodes"]) == 1
    entry = result["nodes"][0]
    assert entry["error"] == "node_not_found"
    assert entry["node_id"] == str(node_id)
    assert "message" in entry


@pytest.mark.asyncio
async def test_get_mixed_found_and_not_found(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    id_found = uuid.uuid4()
    id_missing = uuid.uuid4()
    node = _make_node(node_id=id_found)
    mock_context_service.get.side_effect = [node, None]

    result = await _context_get(
        node_ids=[str(id_found), str(id_missing)],
        silo_id=_SILO_ID,
    )

    assert result["nodes"][0]["node_id"] == str(id_found)
    assert result["nodes"][1]["error"] == "node_not_found"


# ---------------------------------------------------------------------------
# Tests: error handling / bad inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invalid_node_id_format(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    result = await _context_get(node_ids="not-a-uuid", silo_id=_SILO_ID)

    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["error"] == "invalid_node_id"
    assert result["nodes"][0]["node_id"] == "not-a-uuid"
    mock_context_service.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_invalid_silo_id_format(mock_auth, mock_context_service, mock_metrics):
    with (
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        from context_service.mcp.tools.context_get import _context_get

        result = await _context_get(
            node_ids=str(uuid.uuid4()),
            silo_id="not-a-uuid",
        )

    assert result["error"] == "invalid_silo_id"
    assert result["silo_id"] == "not-a-uuid"


@pytest.mark.asyncio
async def test_get_silo_ownership_denied(mock_auth, mock_context_service, mock_metrics):
    deny_response = {"error": "forbidden", "message": "Silo does not belong to org"}
    with (
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=deny_response,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
    ):
        from context_service.mcp.tools.context_get import _context_get

        result = await _context_get(
            node_ids=str(uuid.uuid4()),
            silo_id=_SILO_ID,
        )

    assert result["error"] == "forbidden"


# ---------------------------------------------------------------------------
# Tests: access event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_emits_access_event_for_found_nodes(
    mock_auth, mock_context_service, mock_silo_valid, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    node_id = uuid.uuid4()
    mock_context_service.get.return_value = _make_node(node_id=node_id)

    fake_redis = MagicMock()
    with (
        patch("context_service.mcp.tools.context_get.get_redis", return_value=fake_redis),
        patch(
            "context_service.mcp.tools.context_get.emit_access_event",
            new_callable=AsyncMock,
        ) as mock_emit,
    ):
        result = await _context_get(node_ids=str(node_id), silo_id=_SILO_ID)

    assert result["nodes"][0]["node_id"] == str(node_id)
    mock_emit.assert_called_once_with(fake_redis, _SILO_ID, str(node_id))


@pytest.mark.asyncio
async def test_get_no_access_event_when_redis_unavailable(
    mock_auth, mock_context_service, mock_silo_valid, mock_redis_none, mock_metrics
):
    from context_service.mcp.tools.context_get import _context_get

    node_id = uuid.uuid4()
    mock_context_service.get.return_value = _make_node(node_id=node_id)

    with patch(
        "context_service.mcp.tools.context_get.emit_access_event",
        new_callable=AsyncMock,
    ) as mock_emit:
        await _context_get(node_ids=str(node_id), silo_id=_SILO_ID)

    mock_emit.assert_not_called()
