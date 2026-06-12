"""Tests for epistemic fusion wiring in _context_query (sprint step 1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class _FakeFusedResult:
    node_id: str
    rrf_score: float
    channel_contributions: dict = field(default_factory=dict)
    content: str | None = None
    layer: str | None = None
    confidence: float | None = None
    conflict_status: str | None = None
    created_at: datetime | None = None
    tags: list[str] | None = None


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

    low_evidence = _FakeFusedResult(
        node_id="00000000-0000-0000-0000-000000000001",
        rrf_score=0.80,
        content="unsourced claim",
        layer="knowledge",
        confidence=0.1,
        conflict_status="none",
    )
    high_evidence = _FakeFusedResult(
        node_id="00000000-0000-0000-0000-000000000002",
        rrf_score=0.70,
        content="corroborated fact",
        layer="knowledge",
        confidence=1.0,
        conflict_status="none",
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
        patch("context_service.mcp.tools.context_query.FusionRetriever") as mock_fr_cls,
    ):
        mock_fr_cls.return_value.retrieve = AsyncMock(return_value=[low_evidence, high_evidence])
        mock_svc.return_value.query = AsyncMock(return_value=[])

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    # fused: low = 0.80 * (0.5 + 0.5*0.1) = 0.44; high = 0.70 * 1.0 = 0.70
    assert ids[0] == "00000000-0000-0000-0000-000000000002"
    assert ids[1] == "00000000-0000-0000-0000-000000000001"
    low_dict = next(r for r in result["results"] if "000001" in r["node_id"])
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

    low_evidence = _FakeFusedResult(
        node_id="00000000-0000-0000-0000-000000000001",
        rrf_score=0.80,
        content="unsourced claim",
        layer="knowledge",
        confidence=0.1,
        conflict_status="none",
    )
    high_evidence = _FakeFusedResult(
        node_id="00000000-0000-0000-0000-000000000002",
        rrf_score=0.70,
        content="corroborated fact",
        layer="knowledge",
        confidence=1.0,
        conflict_status="none",
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
        patch("context_service.mcp.tools.context_query.FusionRetriever") as mock_fr_cls,
    ):
        mock_fr_cls.return_value.retrieve = AsyncMock(return_value=[low_evidence, high_evidence])
        mock_svc.return_value.query = AsyncMock(return_value=[])

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    assert ids[0] == "00000000-0000-0000-0000-000000000001"
    assert ids[1] == "00000000-0000-0000-0000-000000000002"
    assert result["results"][0].get("epistemic") is None
