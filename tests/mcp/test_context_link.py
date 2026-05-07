"""Tests for context_link tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fakes.fake_graph_store import FakeGraphStore


@pytest.fixture
def mock_deps():
    with (
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new_callable=AsyncMock,
        ) as auth_mock,
        patch("context_service.mcp.tools.context_link.get_context_service") as svc_mock,
        patch("context_service.mcp.tools.context_link.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_link.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        svc.link.return_value = str(uuid.uuid4())
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_link_creates_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=from_id,
        to_node=to_id,
        relationship="REFERENCES",
    )

    assert "edge_id" in result
    assert result["from_node"] == from_id
    assert result["to_node"] == to_id
    assert result["relationship"] == "REFERENCES"
    assert "created_at" in result
    mock_deps["svc"].link.assert_called_once()


@pytest.mark.asyncio
async def test_link_all_relationship_types(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    silo = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
    for rel in ["REFERENCES", "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO"]:
        result = await _context_link(
            silo_id=silo,
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship=rel,
        )
        assert "error" not in result, f"Failed for {rel}: {result}"


@pytest.mark.asyncio
async def test_link_invalid_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="INVALID_REL",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "valid_values" in result["error"]["details"]


@pytest.mark.asyncio
async def test_link_invalid_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "silo_id must be a valid UUID"}},
    ):
        result = await _context_link(
            silo_id="not-a-uuid",
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_link_wrong_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"success": False, "error": {"code": "NOT_FOUND", "message": "Silo does not exist or org_id mismatch."}},
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid4()),
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["success"] is False
    assert result["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_link_with_weight_and_note(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="SUPPORTS",
        weight=0.7,
        note="Strong structural support",
    )

    assert result.get("success") is not False
    call_kwargs = mock_deps["svc"].link.call_args.kwargs
    assert call_kwargs["weight"] == 0.7
    assert call_kwargs["note"] == "Strong structural support"


@pytest.mark.asyncio
async def test_link_invalid_weight(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="REFERENCES",
        weight=99.9,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_link_passes_correct_relationship_to_service(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node="node-a",
        to_node="node-b",
        relationship="CONTRADICTS",
    )

    call_kwargs = mock_deps["svc"].link.call_args.kwargs
    assert call_kwargs["relationship"] == "CONTRADICTS"
    assert call_kwargs["from_node"] == "node-a"
    assert call_kwargs["to_node"] == "node-b"


# ---------------------------------------------------------------------------
# Outcome-verification tests using FakeGraphStore + real ContextService
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_graph_store() -> FakeGraphStore:
    return FakeGraphStore()


@pytest.fixture
def real_context_service(fake_graph_store: FakeGraphStore):
    """ContextService wired to FakeGraphStore; Qdrant/cache/embedding stubbed."""
    from unittest.mock import MagicMock

    from context_service.services.context import ContextService

    qdrant_stub = MagicMock()
    return ContextService(memgraph=fake_graph_store, qdrant=qdrant_stub)


@pytest.fixture
def mock_deps_real_svc(real_context_service):
    """Same auth/silo patches as mock_deps but injects the real ContextService."""
    with (
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new_callable=AsyncMock,
        ) as auth_mock,
        patch(
            "context_service.mcp.tools.context_link.get_context_service",
            return_value=real_context_service,
        ),
        patch("context_service.mcp.tools.context_link.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_link.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth
        yield


@pytest.mark.asyncio
async def test_link_writes_edge_to_graph_store(fake_graph_store, mock_deps_real_svc):
    """Edge creation query must land in FakeGraphStore.write_log."""
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    result = await _context_link(
        silo_id=silo_id,
        from_node=from_id,
        to_node=to_id,
        relationship="REFERENCES",
    )

    assert result.get("success") is not False
    assert len(fake_graph_store.write_log) == 1
    cypher, params = fake_graph_store.write_log[0]
    assert "CREATE" in cypher
    assert "REFERENCES" in cypher
    assert params["from_id"] == from_id
    assert params["to_id"] == to_id
    assert "id" in params["props"]
    assert params["props"]["id"] == result["edge_id"]


@pytest.mark.asyncio
async def test_link_write_log_contains_weight(fake_graph_store, mock_deps_real_svc):
    """Weight parameter must be forwarded to the Cypher write."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="SUPPORTS",
        weight=0.42,
    )

    assert len(fake_graph_store.write_log) == 1
    _, params = fake_graph_store.write_log[0]
    assert params["props"]["weight"] == 0.42


@pytest.mark.asyncio
async def test_link_write_log_contains_note(fake_graph_store, mock_deps_real_svc):
    """Optional note must appear in the edge props when provided."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="DERIVED_FROM",
        note="upstream source",
    )

    _, params = fake_graph_store.write_log[0]
    assert params["props"]["note"] == "upstream source"


@pytest.mark.asyncio
async def test_link_no_write_on_invalid_relationship(fake_graph_store, mock_deps_real_svc):
    """Invalid relationship must be rejected before any write hits the store."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    result = await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="NOT_A_REAL_REL",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert fake_graph_store.write_log == []


@pytest.mark.asyncio
async def test_link_no_write_on_invalid_weight(fake_graph_store, mock_deps_real_svc):
    """Out-of-range weight must be rejected before any write hits the store."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    result = await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="REFERENCES",
        weight=99.9,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert fake_graph_store.write_log == []


@pytest.mark.asyncio
async def test_link_relationship_type_in_cypher(fake_graph_store, mock_deps_real_svc):
    """Each relationship type must appear verbatim in the generated Cypher."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    for rel in ["REFERENCES", "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO"]:
        fake_graph_store._write_log.clear()
        await _context_link(
            silo_id=silo_id,
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship=rel,
        )
        cypher, _ = fake_graph_store.write_log[0]
        assert rel in cypher, f"Expected {rel!r} in Cypher but got: {cypher}"
