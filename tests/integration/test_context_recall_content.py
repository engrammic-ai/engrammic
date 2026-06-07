"""Tests for context_recall include_content flag."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_query_cache_singletons():
    """Reset context_query's module-global cache singletons to isolate tests.

    context_query holds ``_result_cache`` / ``_rerank_cache`` as process-level
    globals. Without a per-test reset, a cached result dict populated by another
    test in the suite can be served to these tests, masking the tier field and
    making results pass standalone but fail in the full suite.
    """
    import context_service.mcp.tools.context_query as _cq

    _cq._result_cache = None
    _cq._rerank_cache = None
    yield
    _cq._result_cache = None
    _cq._rerank_cache = None


def _full_node(
    node_id: str, *, layer: str = "memory", content: str = "hello world", tier: str = "HOT"
) -> dict:
    return {
        "node_id": node_id,
        "content": content,
        "type": "context",
        "silo_id": str(uuid4()),
        "properties": {"foo": "bar"},
        "source_uri": None,
        "content_hash": "abc123",
        "layer": layer,
        "summary": None,
        "confidence": 0.9,
        "tags": ["t1"],
        "created_at": "2026-05-07T00:00:00+00:00",
        "tier": tier,
    }


@pytest.mark.asyncio
async def test_include_content_true_is_default_and_preserves_full_node() -> None:
    """Default behavior returns the full node payload (backward compatible)."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid)

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid])

        assert result["nodes"][0] == full


@pytest.mark.asyncio
async def test_include_content_false_projects_node_in_flat_get() -> None:
    """include_content=False strips content and reduces nodes to the projection."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="x" * 500)

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=False)

        node = result["nodes"][0]
        assert set(node.keys()) == {
            "node_id",
            "layer",
            "summary",
            "created_at",
            "confidence",
            "tier",
            "relevance_score",
        }
        assert node["node_id"] == nid
        assert node["layer"] == "memory"
        assert node["confidence"] == 0.9
        assert node["created_at"] == "2026-05-07T00:00:00+00:00"
        # No pre-computed summary - falls back to first 200 chars of content
        assert node["summary"] == "x" * 200
        assert "content" not in node
        assert "properties" not in node


@pytest.mark.asyncio
async def test_include_content_false_preserves_existing_summary() -> None:
    """When the node already has a summary, it is used as-is (not truncated content)."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="x" * 500)
    full["summary"] = "pre-computed summary"

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=False)

        assert result["nodes"][0]["summary"] == "pre-computed summary"


@pytest.mark.asyncio
async def test_summary_truncates_at_200_chars() -> None:
    """Content longer than 200 chars is truncated; shorter content is returned whole."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid_long = str(uuid4())
    nid_short = str(uuid4())
    silo_id = str(uuid4())
    long_node = _full_node(nid_long, content="a" * 350)
    short_node = _full_node(nid_short, content="brief")

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [long_node, short_node]}

        result = await _context_recall(
            silo_id=silo_id,
            node_ids=[nid_long, nid_short],
            include_content=False,
        )

        long_out = next(n for n in result["nodes"] if n["node_id"] == nid_long)
        short_out = next(n for n in result["nodes"] if n["node_id"] == nid_short)
        assert len(long_out["summary"]) == 200
        assert long_out["summary"] == "a" * 200
        assert short_out["summary"] == "brief"


@pytest.mark.asyncio
async def test_node_ids_always_returned_regardless_of_flag() -> None:
    """node_id is always present whether include_content is True or False."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid)

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        with_content = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=True)
        mock_get.return_value = {"nodes": [_full_node(nid)]}
        without_content = await _context_recall(
            silo_id=silo_id, node_ids=[nid], include_content=False
        )

        assert with_content["nodes"][0]["node_id"] == nid
        assert without_content["nodes"][0]["node_id"] == nid


@pytest.mark.asyncio
async def test_include_content_false_in_query_mode() -> None:
    """Search results are stripped to the projection when include_content=False."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    search_hit = {
        "node_id": nid,
        "layer": "knowledge",
        "content": "y" * 300,
        "summary": None,
        "confidence": 0.7,
        "relevance_score": 0.85,
        "tags": [],
        "created_at": "2026-05-07T00:00:00+00:00",
    }

    with patch("context_service.mcp.tools.context_recall._context_query") as mock_query:
        mock_query.return_value = {
            "results": [search_hit],
            "total_candidates": 1,
            "search_time_ms": 12,
        }

        result = await _context_recall(silo_id=silo_id, query="anything", include_content=False)

        out = result["results"][0]
        assert set(out.keys()) == {
            "node_id",
            "layer",
            "summary",
            "created_at",
            "confidence",
            "tier",
            "relevance_score",
        }
        assert out["node_id"] == nid
        assert out["layer"] == "knowledge"
        assert out["summary"] == "y" * 200
        # Top-level metadata is preserved
        assert result["total_candidates"] == 1
        assert result["search_time_ms"] == 12


@pytest.mark.asyncio
async def test_include_content_false_in_graph_mode() -> None:
    """Graph traversal nodes are also projected; edges and stats are untouched."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    graph_node = {
        "node_id": nid,
        "type": "context",
        "content": "z" * 250,
        "layer": "memory",
        "confidence": 0.6,
    }
    edges = [{"from_node": nid, "to_node": str(uuid4()), "relationship": "RELATES_TO"}]

    with patch("context_service.mcp.tools.context_recall._context_graph") as mock_graph:
        mock_graph.return_value = {
            "nodes": [graph_node],
            "edges": edges,
            "traversal_stats": {"depth_reached": 1, "nodes_visited": 1, "edges_traversed": 1},
            "metadata": {},
        }

        result = await _context_recall(
            silo_id=silo_id,
            node_ids=[nid],
            depth=1,
            include_content=False,
        )

        out = result["nodes"][0]
        assert set(out.keys()) == {
            "node_id",
            "layer",
            "summary",
            "created_at",
            "confidence",
            "tier",
            "relevance_score",
        }
        assert out["summary"] == "z" * 200
        # Graph nodes lack created_at; projection preserves None
        assert out["created_at"] is None
        # Edges and stats are untouched
        assert result["edges"] == edges
        assert result["traversal_stats"]["edges_traversed"] == 1


@pytest.mark.asyncio
async def test_include_content_false_passes_through_error_entries() -> None:
    """Sentinel error entries (no node_id) are not projected away."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid)
    error_entry = {"error": "invalid_node_id", "node_id": "not-a-uuid"}

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full, error_entry]}

        result = await _context_recall(
            silo_id=silo_id,
            node_ids=[nid, "not-a-uuid"],
            include_content=False,
        )

        # Error entries with a node_id field still go through projection;
        # entries without node_id pass through. The contract: callers can
        # always rely on seeing the error sentinel.
        errors = [n for n in result["nodes"] if n.get("error")]
        assert len(errors) == 1


@pytest.mark.asyncio
async def test_cold_node_returns_summary_by_default() -> None:
    """COLD tier nodes should return summary instead of content when include_content=None."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="x" * 500, tier="COLD")
    full["summary"] = "pre-computed summary"

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=None)

        node = result["nodes"][0]
        assert "summary" in node
        assert "expandable" in node
        assert node["expandable"] is True
        assert "content" not in node


@pytest.mark.asyncio
async def test_hot_node_returns_content_by_default() -> None:
    """HOT tier nodes should return full content when include_content=None."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="full content here", tier="HOT")

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=None)

        node = result["nodes"][0]
        assert "content" in node
        assert node["content"] == "full content here"


@pytest.mark.asyncio
async def test_warm_node_returns_content_by_default() -> None:
    """WARM tier nodes should return full content when include_content=None."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="warm content here", tier="WARM")

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=None)

        node = result["nodes"][0]
        assert "content" in node
        assert node["content"] == "warm content here"


@pytest.mark.asyncio
async def test_include_content_true_overrides_cold_tier() -> None:
    """Explicit include_content=True should return full content even for COLD nodes."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="full content", tier="COLD")

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=True)

        node = result["nodes"][0]
        assert "content" in node
        assert node["content"] == "full content"


# ---------------------------------------------------------------------------
# TDD: tier propagation for search (query) results
# ---------------------------------------------------------------------------


def _make_query_result(
    node_id: str,
    *,
    tier: str | None,
    content: str = "full content here",
    layer: str = "memory",
) -> Any:
    """Build a QueryResult-like object for mocking ctx_svc.query()."""
    import uuid as _uuid
    from datetime import UTC, datetime

    from context_service.services.models import QueryResult

    return QueryResult(
        node_id=_uuid.UUID(node_id),
        layer=layer,
        content=content,
        confidence=0.9,
        relevance_score=0.8,
        summary=None,
        tags=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        conflict_status="none",
        credibility=0.0,
        credibility_factors=None,
        tier=tier,
    )


def _make_query_mocks(query_results: list) -> tuple:
    """Return (auth_mock, ctx_svc_mock, silo_svc_mock) for _context_query patching."""
    from unittest.mock import AsyncMock, MagicMock

    auth = MagicMock()
    auth.org_id = "org-test"

    ctx_svc = MagicMock()
    ctx_svc.query = AsyncMock(return_value=query_results)
    ctx_svc.embedding_client = None
    ctx_svc.vector_store = None

    silo_svc = MagicMock()
    silo_svc.get_by_id = AsyncMock(return_value=None)

    return auth, ctx_svc, silo_svc


@pytest.mark.asyncio
async def test_tier_is_propagated_to_search_result_dicts() -> None:
    """context_query result dicts must carry the 'tier' field from QueryResult.

    This is the red-first test: before propagating tier through QueryResult and
    raw_result_dicts, the 'tier' key is absent from result dicts, making the
    tier-based content policy treat every search result as COLD.
    """
    import uuid as _uuid

    from context_service.mcp.tools.context_query import _context_query

    hot_id = str(_uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    cold_id = str(_uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))

    hot_result = _make_query_result(hot_id, tier="HOT", content="hot content")
    cold_result = _make_query_result(cold_id, tier="COLD", content="cold content")

    auth, ctx_svc, silo_svc = _make_query_mocks([hot_result, cold_result])

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        result = await _context_query(silo_id="silo-1", query="anything")

    assert "error" not in result
    result_by_id = {r["node_id"]: r for r in result["results"]}

    # Both results must carry a 'tier' key
    assert "tier" in result_by_id[hot_id], "HOT result is missing 'tier' field"
    assert "tier" in result_by_id[cold_id], "COLD result is missing 'tier' field"

    assert result_by_id[hot_id]["tier"] == "HOT"
    assert result_by_id[cold_id]["tier"] == "COLD"


def test_tier_policy_keeps_hot_strips_cold_for_search_results() -> None:
    """With tier propagated onto search-result dicts, the include_content=None
    tier policy keeps HOT content and strips COLD to a summary.

    Paired with test_tier_is_propagated_to_search_result_dicts (which proves the
    real query path now carries 'tier'), this verifies the end goal of tier
    propagation: the policy can finally distinguish HOT/WARM from COLD for search
    results instead of defaulting every result to COLD.
    """
    from context_service.mcp.tools.context_recall import _apply_tier_content_policy

    response = {
        "results": [
            {
                "node_id": "hot",
                "layer": "memory",
                "content": "hot content here",
                "summary": None,
                "confidence": 0.9,
                "relevance_score": 0.8,
                "created_at": None,
                "tier": "HOT",
            },
            {
                "node_id": "cold",
                "layer": "memory",
                "content": "x" * 300,
                "summary": "cold summary",
                "confidence": 0.9,
                "relevance_score": 0.8,
                "created_at": None,
                "tier": "COLD",
            },
        ]
    }

    out = _apply_tier_content_policy(response, None)
    by_id = {r["node_id"]: r for r in out["results"]}

    # HOT retains full content
    assert by_id["hot"].get("content") == "hot content here"
    # COLD is stripped to its summary
    assert "content" not in by_id["cold"]
    assert by_id["cold"]["summary"] == "cold summary"
