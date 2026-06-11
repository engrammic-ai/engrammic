"""Tests for epistemic fusion wiring in _context_query (sprint step 1)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class _FakeQueryResult:
    node_id: str
    layer: str
    content: str
    confidence: float
    relevance_score: float
    summary: str | None = None
    tags: list[str] | None = None
    created_at: None = None
    conflict_status: str = "none"
    credibility: float = 0.0
    credibility_factors: dict | None = None
    tier: str | None = None
    superseded_by: str | None = None


def _settings(fusion_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.reranking.enabled = False  # isolate fusion from reranking
    s.reranking.adaptive_threshold_enabled = False
    s.reranking.expand_hard_queries = False
    s.causal.query_enabled = False
    s.epistemic_fusion.enabled = fusion_enabled
    s.epistemic_fusion.confidence_weight = 0.5
    s.epistemic_fusion.conflict_penalty = 0.5
    s.result_cache.memory_ttl = 300
    s.result_cache.knowledge_ttl = 3600
    s.result_cache.wisdom_ttl = 1800
    return s


def _silo_service() -> MagicMock:
    silo = MagicMock()
    silo.metadata = {}
    svc = MagicMock()
    svc.get_by_id = AsyncMock(return_value=silo)
    return svc


@pytest.mark.asyncio
async def test_fusion_reorders_and_surfaces_breakdown() -> None:
    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    low_evidence = _FakeQueryResult(
        node_id="low",
        layer="knowledge",
        content="unsourced claim",
        confidence=0.1,
        relevance_score=0.80,
    )
    high_evidence = _FakeQueryResult(
        node_id="high",
        layer="knowledge",
        content="corroborated fact",
        confidence=1.0,
        relevance_score=0.70,
        superseded_by=None,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_silo_service(),
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=_settings(),
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        mock_svc.return_value.query = AsyncMock(return_value=[low_evidence, high_evidence])
        mock_svc.return_value.vector_store = None
        mock_svc.return_value.embedding_client = None

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    # fused: low = 0.80 * (0.5 + 0.5*0.1) = 0.44; high = 0.70 * 1.0 = 0.70
    assert ids == ["high", "low"]
    low_dict = next(r for r in result["results"] if r["node_id"] == "low")
    assert low_dict["epistemic"]["confidence_factor"] == pytest.approx(0.55)
    assert low_dict["epistemic"]["multiplier"] == pytest.approx(0.55)
    assert low_dict["relevance_score"] == pytest.approx(0.44)
    assert "superseded_by" in low_dict
    # Reranking did not run, so no rerank_score basis is exposed.
    assert low_dict["rerank_score"] is None


@pytest.mark.asyncio
async def test_fusion_disabled_preserves_order() -> None:
    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    low_evidence = _FakeQueryResult(
        node_id="low",
        layer="knowledge",
        content="unsourced claim",
        confidence=0.1,
        relevance_score=0.80,
    )
    high_evidence = _FakeQueryResult(
        node_id="high",
        layer="knowledge",
        content="corroborated fact",
        confidence=1.0,
        relevance_score=0.70,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_silo_service(),
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=_settings(fusion_enabled=False),
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        mock_svc.return_value.query = AsyncMock(return_value=[low_evidence, high_evidence])
        mock_svc.return_value.vector_store = None
        mock_svc.return_value.embedding_client = None

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    assert ids == ["low", "high"]
    assert result["results"][0].get("epistemic") is None
