# tests/mcp/tools/test_update.py
"""Tests for update tool - explicit supersession with built-in semantic search."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.update import _update_impl

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_ORG_ID = "test-org"
_TARGET_ID = str(uuid.uuid4())
_NEW_NODE_ID = str(uuid.uuid4())


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = _ORG_ID
    auth.agent_id = "agent:test"
    auth.db_user_id = None
    return auth


@pytest.fixture
def mock_mcp_context(mock_auth):
    with (
        patch(
            "context_service.mcp.tools.update.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch(
            "context_service.mcp.tools.update.track_tool_usage",
            new=AsyncMock(),
        ),
    ):
        yield mock_auth


@pytest.fixture
def mock_assert_success():
    """Mock _context_assert to return a successful node creation result."""
    with patch(
        "context_service.mcp.tools.update._context_assert",
        new=AsyncMock(
            return_value={
                "node_id": _NEW_NODE_ID,
                "layer": "knowledge",
                "claim_type": "freeform",
                "evidence_status": "verified",
                "evidence_nodes": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "supersedes": _TARGET_ID,
            }
        ),
    ) as m:
        yield m


@pytest.fixture
def mock_validate_target_valid():
    """Mock validate_supersession_target to return None (target is valid/current head)."""
    with patch(
        "context_service.mcp.tools.update.validate_supersession_target",
        new=AsyncMock(return_value=None),
    ) as m:
        yield m


@pytest.fixture
def mock_validate_target_already_superseded():
    """Mock validate_supersession_target to indicate target was already superseded."""
    head_id = str(uuid.uuid4())
    with patch(
        "context_service.mcp.tools.update.validate_supersession_target",
        new=AsyncMock(
            return_value={
                "error": "already_superseded",
                "message": f"Node {_TARGET_ID} was already superseded",
                "head_id": head_id,
                "hint": "Supersede the head node instead",
            }
        ),
    ) as m:
        yield m, head_id


@pytest.fixture
def mock_context_service_with_graph():
    """Mock context service with graph store for node fetching."""
    svc = MagicMock()
    svc.graph_store = MagicMock()
    svc.graph_store.execute_query = AsyncMock(
        return_value=[{"n": {"content": "Old content about the topic", "created_at": "2026-01-01T00:00:00"}, "_labels": ["Claim"]}]
    )
    svc.vector_store = MagicMock()
    with patch(
        "context_service.mcp.tools.update.get_context_service",
        return_value=svc,
    ):
        yield svc


@pytest.fixture
def mock_supersession_metric():
    with patch("context_service.mcp.tools.update.record_supersession_used") as m:
        yield m


# --- Behavior matrix tests ---


@pytest.mark.asyncio
async def test_neither_query_nor_target_returns_error(mock_mcp_context):
    """When neither query nor target is provided, return an error."""
    result = await _update_impl(
        content="Updated claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
    )
    assert result["error"] == "missing_target"
    assert "query or target" in result["message"]


@pytest.mark.asyncio
async def test_direct_target_supersession_success(
    mock_mcp_context,
    mock_validate_target_valid,
    mock_assert_success,
    mock_context_service_with_graph,
    mock_supersession_metric,
):
    """With explicit target, performs direct supersession via learn."""
    result = await _update_impl(
        content="Updated claim content",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
        target=_TARGET_ID,
    )
    assert result["status"] == "updated"
    assert result["node_id"] == _NEW_NODE_ID
    assert result["superseded_id"] == _TARGET_ID
    assert "superseded_content" in result
    mock_assert_success.assert_called_once()
    called_kwargs = mock_assert_success.call_args
    assert called_kwargs.kwargs["supersedes"] == _TARGET_ID


@pytest.mark.asyncio
async def test_target_already_superseded_returns_error(
    mock_mcp_context,
    mock_validate_target_already_superseded,
):
    """If target was already superseded, return error with head_id hint."""
    mock_patch, head_id = mock_validate_target_already_superseded
    result = await _update_impl(
        content="Updated claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
        target=_TARGET_ID,
    )
    assert result["status"] == "error"
    assert result["error"] == "already_superseded"
    assert "successor" in result["message"]
    assert result["head_id"] == head_id


@pytest.mark.asyncio
async def test_query_single_match_auto_supersedes(
    mock_mcp_context,
    mock_assert_success,
    mock_context_service_with_graph,
    mock_supersession_metric,
):
    """With query and exactly 1 match above threshold, auto-supersede it."""
    from context_service.stores.qdrant import SearchResult

    single_match = SearchResult(node_id=_TARGET_ID, score=0.85, payload={})
    mock_context_service_with_graph.vector_store.search = AsyncMock(return_value=[single_match])

    with patch(
        "context_service.mcp.tools.update.embed",
        new=AsyncMock(return_value=[0.1] * 128),
    ):
        result = await _update_impl(
            content="Improved knowledge",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            query="original knowledge topic",
        )

    assert result["status"] == "updated"
    assert result["superseded_id"] == _TARGET_ID
    called_kwargs = mock_assert_success.call_args
    assert called_kwargs.kwargs["supersedes"] == _TARGET_ID


@pytest.mark.asyncio
async def test_query_multiple_matches_returns_ambiguous(
    mock_mcp_context,
    mock_context_service_with_graph,
):
    """With query matching 2+ nodes above threshold, return ambiguous status."""
    from context_service.stores.qdrant import SearchResult

    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    id3 = str(uuid.uuid4())
    matches = [
        SearchResult(node_id=id1, score=0.92, payload={}),
        SearchResult(node_id=id2, score=0.85, payload={}),
        SearchResult(node_id=id3, score=0.78, payload={}),
    ]
    mock_context_service_with_graph.vector_store.search = AsyncMock(return_value=matches)
    mock_context_service_with_graph.graph_store.execute_query = AsyncMock(
        return_value=[{"n": {"content": "Some content here", "created_at": "2026-01-01"}, "_labels": ["Claim"]}]
    )

    with patch(
        "context_service.mcp.tools.update.embed",
        new=AsyncMock(return_value=[0.1] * 128),
    ):
        result = await _update_impl(
            content="Improved knowledge",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            query="ambiguous topic",
        )

    assert result["status"] == "ambiguous"
    assert "candidates" in result
    assert len(result["candidates"]) >= 2
    # Ordered by similarity descending
    scores = [c["similarity"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_query_no_matches_returns_not_found(
    mock_mcp_context,
    mock_context_service_with_graph,
):
    """With query matching no nodes, return not_found status."""
    mock_context_service_with_graph.vector_store.search = AsyncMock(return_value=[])

    with patch(
        "context_service.mcp.tools.update.embed",
        new=AsyncMock(return_value=[0.1] * 128),
    ):
        result = await _update_impl(
            content="Improved knowledge",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            query="very specific topic that does not exist",
        )

    assert result["status"] == "not_found"
    assert "learn()" in result["message"]


@pytest.mark.asyncio
async def test_candidates_snippet_truncated_at_200_chars(
    mock_mcp_context,
    mock_assert_success,
    mock_context_service_with_graph,
    mock_supersession_metric,
):
    """Candidate content snippets are truncated to 200 characters."""
    from context_service.stores.qdrant import SearchResult

    long_content = "A" * 500
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    matches = [
        SearchResult(node_id=id1, score=0.91, payload={}),
        SearchResult(node_id=id2, score=0.81, payload={}),
    ]
    mock_context_service_with_graph.vector_store.search = AsyncMock(return_value=matches)
    mock_context_service_with_graph.graph_store.execute_query = AsyncMock(
        return_value=[{"n": {"content": long_content, "created_at": "2026-01-01"}, "_labels": ["Claim"]}]
    )

    with patch(
        "context_service.mcp.tools.update.embed",
        new=AsyncMock(return_value=[0.1] * 128),
    ):
        result = await _update_impl(
            content="Improved knowledge",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            query="long content topic",
        )

    assert result["status"] == "ambiguous"
    for candidate in result["candidates"]:
        assert len(candidate["content"]) <= 200


@pytest.mark.asyncio
async def test_context_assert_error_propagates(
    mock_mcp_context,
    mock_validate_target_valid,
    mock_context_service_with_graph,
):
    """If _context_assert returns an error, propagate it."""
    with patch(
        "context_service.mcp.tools.update._context_assert",
        new=AsyncMock(return_value={"error": "invalid_evidence", "evidence": "bad://url", "reason": "unreachable"}),
    ):
        result = await _update_impl(
            content="Updated claim",
            evidence=["bad://url"],
            target=_TARGET_ID,
        )

    assert result["error"] == "invalid_evidence"


@pytest.mark.asyncio
async def test_neither_query_nor_target_has_status_key(mock_mcp_context):
    """The error response for missing target includes a status key."""
    result = await _update_impl(
        content="Updated claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
    )
    assert result["status"] == "error"
    assert result["error"] == "missing_target"


@pytest.mark.asyncio
async def test_target_non_claim_node_rejected(
    mock_mcp_context,
    mock_validate_target_valid,
):
    """When target node is not a Claim, return a wrong_layer error."""
    svc = MagicMock()
    svc.graph_store = MagicMock()
    # Simulate a Memory node (not a Claim)
    svc.graph_store.execute_query = AsyncMock(
        return_value=[{"n": {"content": "some memory", "created_at": "2026-01-01"}, "_labels": ["Memory"]}]
    )
    svc.vector_store = MagicMock()

    with patch(
        "context_service.mcp.tools.update.get_context_service",
        return_value=svc,
    ):
        result = await _update_impl(
            content="Updated claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            target=_TARGET_ID,
        )

    assert result["status"] == "error"
    assert result["error"] == "wrong_layer"
    assert result["actual_label"] == "Memory"
    assert "Knowledge-layer only" in result["message"]


@pytest.mark.asyncio
async def test_target_claim_node_proceeds(
    mock_mcp_context,
    mock_validate_target_valid,
    mock_assert_success,
    mock_supersession_metric,
):
    """When target node is a Claim, layer check passes and supersession proceeds."""
    svc = MagicMock()
    svc.graph_store = MagicMock()
    # First call: layer check (GET_NODE_INTERNAL), second call: fetch superseded content
    svc.graph_store.execute_query = AsyncMock(
        return_value=[
            {"n": {"content": "existing claim", "created_at": "2026-01-01"}, "_labels": ["Claim"]}
        ]
    )
    svc.vector_store = MagicMock()

    with patch(
        "context_service.mcp.tools.update.get_context_service",
        return_value=svc,
    ):
        result = await _update_impl(
            content="Updated claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            target=_TARGET_ID,
        )

    assert result["status"] == "updated"
    assert result["node_id"] == _NEW_NODE_ID


@pytest.mark.asyncio
async def test_confidence_and_source_tier_passed_through(
    mock_mcp_context,
    mock_validate_target_valid,
    mock_assert_success,
    mock_context_service_with_graph,
    mock_supersession_metric,
):
    """confidence and source_tier params are forwarded to _context_assert."""
    await _update_impl(
        content="Updated claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
        target=_TARGET_ID,
        confidence=0.95,
        source_tier="authoritative",
    )
    called_kwargs = mock_assert_success.call_args
    assert called_kwargs.kwargs["confidence"] == 0.95
    assert called_kwargs.kwargs["source_tier"] == "authoritative"
