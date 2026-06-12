"""Tests for context_query reranking integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.reranker import RerankResult


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


class TestContextQueryReranking:
    @pytest.mark.asyncio
    async def test_query_with_reranking_enabled(self) -> None:
        """Test that FusionRetriever is called (which handles reranking internally)."""
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        fused_results = [
            _FakeFusedResult(
                node_id="00000000-0000-0000-0000-000000000001",
                rrf_score=0.8,
                layer="memory",
                content="First result",
                confidence=0.9,
                conflict_status="none",
            ),
            _FakeFusedResult(
                node_id="00000000-0000-0000-0000-000000000002",
                rrf_score=0.7,
                layer="memory",
                content="Second result - no longer viable",
                confidence=0.85,
                conflict_status="none",
            ),
        ]

        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.causal = MagicMock()
        mock_settings.causal.query_enabled = False
        mock_settings.epistemic_fusion.enabled = False

        mock_silo = MagicMock()
        mock_silo.freshness_decay_lambda = 0.01
        mock_silo.default_recall_threshold = 0.5
        mock_silo.metadata = {}
        mock_silo_service = MagicMock()
        mock_silo_service.get_by_id = AsyncMock(return_value=mock_silo)

        mock_fr = AsyncMock(return_value=fused_results)

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                return_value=mock_auth,
            ),
            patch("context_service.mcp.tools.context_query.get_context_service"),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=mock_silo_service,
            ),
            patch(
                "context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None
            ),
            patch(
                "context_service.mcp.tools.context_query.get_settings", return_value=mock_settings
            ),
            patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
            patch(
                "context_service.mcp.tools.context_query.FusionRetriever"
            ) as mock_fr_cls,
        ):
            mock_fr_cls.return_value.retrieve = mock_fr

            from context_service.mcp.tools.context_query import _context_query

            result = await _context_query(
                silo_id="test-silo",
                query="what was rejected?",
                top_k=10,
            )

            assert "results" in result
            mock_fr.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_with_reranking_disabled(self) -> None:
        """Test that results are returned when FusionRetriever returns results."""
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        fused_results = [
            _FakeFusedResult(
                node_id="00000000-0000-0000-0000-000000000001",
                rrf_score=0.8,
                layer="memory",
                content="First result",
                confidence=0.9,
                conflict_status="none",
            ),
        ]

        mock_settings = MagicMock()
        mock_settings.reranking.enabled = False
        mock_settings.causal = MagicMock()
        mock_settings.causal.query_enabled = False
        mock_settings.epistemic_fusion.enabled = False

        mock_silo = MagicMock()
        mock_silo.freshness_decay_lambda = 0.01
        mock_silo.default_recall_threshold = 0.5
        mock_silo.metadata = {}
        mock_silo_service = MagicMock()
        mock_silo_service.get_by_id = AsyncMock(return_value=mock_silo)

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                return_value=mock_auth,
            ),
            patch("context_service.mcp.tools.context_query.get_context_service"),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=mock_silo_service,
            ),
            patch(
                "context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None
            ),
            patch(
                "context_service.mcp.tools.context_query.get_settings", return_value=mock_settings
            ),
            patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
            patch(
                "context_service.mcp.tools.context_query.FusionRetriever"
            ) as mock_fr_cls,
        ):
            mock_fr_cls.return_value.retrieve = AsyncMock(return_value=fused_results)

            from context_service.mcp.tools.context_query import _context_query

            result = await _context_query(
                silo_id="test-silo",
                query="test query",
                top_k=10,
            )

            assert "results" in result
            assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_apply_reranking_skips_single_result(self) -> None:
        """Test that _apply_reranking returns early when only one result."""
        mock_result = MagicMock(node_id="node-1", content="Only result")
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True

        from context_service.mcp.tools.context_query import _apply_reranking

        output, fallback_used, reranked_applied = await _apply_reranking(
            "query", [mock_result], mock_settings
        )
        assert output == [mock_result]
        assert fallback_used is False
        assert reranked_applied is False

    @pytest.mark.asyncio
    async def test_hard_query_triggers_expansion(self) -> None:
        """Test that hard queries trigger LLM expansion."""
        from context_service.reranking import is_hard_query

        # Verify the query is detected as hard
        assert is_hard_query("what was rejected?") is True
        assert is_hard_query("meeting notes") is False

    @pytest.mark.asyncio
    async def test_apply_reranking_skips_when_no_model(self) -> None:
        """Test that _apply_reranking returns original order when no reranker model configured."""
        mock_results = [
            MagicMock(node_id="node-1", content="First"),
            MagicMock(node_id="node-2", content="Second"),
        ]
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True

        mock_models_config = MagicMock()
        mock_models_config.litellm_reranker_model = None

        with patch(
            "context_service.mcp.tools.context_query.load_models_config",
            return_value=mock_models_config,
        ):
            from context_service.mcp.tools.context_query import _apply_reranking

            output, fallback_used, reranked_applied = await _apply_reranking(
                "query", mock_results, mock_settings
            )
            assert output == mock_results
            assert fallback_used is False
            assert reranked_applied is False

    @pytest.mark.asyncio
    async def test_apply_reranking_fresh_writes_back_scores(self) -> None:
        """After a successful fresh rerank, relevance_score is set to the reranker score."""
        mock_results = [
            MagicMock(node_id="node-1", content="First", relevance_score=0.34),
            MagicMock(node_id="node-2", content="Second", relevance_score=0.80),
        ]
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.reranking.reranker_timeout_seconds = 2.0
        mock_settings.vertex_project = None

        mock_models_config = MagicMock()
        mock_models_config.litellm_reranker_model = "test-model"

        # Reranker returns node-1 at top with a higher score
        reranked = [
            RerankResult(node_id="node-1", score=0.92, original_rank=1),
            RerankResult(node_id="node-2", score=0.55, original_rank=0),
        ]

        with (
            patch(
                "context_service.mcp.tools.context_query.load_models_config",
                return_value=mock_models_config,
            ),
            patch(
                "context_service.mcp.tools.context_query.LiteLLMReranker",
            ) as mock_reranker_cls,
        ):
            mock_reranker_cls.return_value.rerank = AsyncMock(return_value=reranked)

            from context_service.mcp.tools.context_query import _apply_reranking

            output, fallback_used, reranked_applied = await _apply_reranking(
                "query", mock_results, mock_settings
            )

        assert reranked_applied is True
        assert fallback_used is False
        # Scores must be the reranker scores, not the original cosine scores
        score_map = {str(r.node_id): r.relevance_score for r in output}
        assert score_map["node-1"] == 0.92
        assert score_map["node-2"] == 0.55

    @pytest.mark.asyncio
    async def test_apply_reranking_cache_hit_writes_back_scores(self) -> None:
        """After a cache-hit rerank, relevance_score is set to the cached reranker score."""
        mock_results = [
            MagicMock(node_id="node-1", content="First", relevance_score=0.34),
            MagicMock(node_id="node-2", content="Second", relevance_score=0.80),
        ]
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.reranking.reranker_timeout_seconds = 2.0
        mock_settings.vertex_project = None

        mock_models_config = MagicMock()
        mock_models_config.litellm_reranker_model = "test-model"

        # Cache returns scores in descending order
        cached_scores: list[tuple[str, float]] = [
            ("node-1", 0.88),
            ("node-2", 0.42),
        ]
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=cached_scores)

        with patch(
            "context_service.mcp.tools.context_query.load_models_config",
            return_value=mock_models_config,
        ):
            from context_service.mcp.tools.context_query import _apply_reranking

            output, fallback_used, reranked_applied = await _apply_reranking(
                "query",
                mock_results,
                mock_settings,
                query_embedding=[0.1, 0.2],
                silo_id="silo-1",
                rerank_cache=mock_cache,
            )

        assert reranked_applied is True
        assert fallback_used is False
        score_map = {str(r.node_id): r.relevance_score for r in output}
        assert score_map["node-1"] == 0.88
        assert score_map["node-2"] == 0.42

    @pytest.mark.asyncio
    async def test_apply_reranking_stale_cache_falls_through_to_fresh(self) -> None:
        """A cache hit whose ids do not match the current results is ignored;
        the function falls through to a fresh rerank instead of reporting
        reranked_applied=True with no scores written."""
        mock_results = [
            MagicMock(node_id="node-1", content="First", relevance_score=0.34),
            MagicMock(node_id="node-2", content="Second", relevance_score=0.80),
        ]
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.reranking.reranker_timeout_seconds = 2.0
        mock_settings.vertex_project = None

        mock_models_config = MagicMock()
        mock_models_config.litellm_reranker_model = "test-model"

        # Stale cache: scores for ids that are not in the current result set.
        stale_scores: list[tuple[str, float]] = [
            ("ghost-1", 0.99),
            ("ghost-2", 0.97),
        ]
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=stale_scores)
        mock_cache.set = AsyncMock()

        # Fresh rerank returns real scores for the actual nodes.
        reranked = [
            RerankResult(node_id="node-1", score=0.91, original_rank=1),
            RerankResult(node_id="node-2", score=0.50, original_rank=0),
        ]

        with (
            patch(
                "context_service.mcp.tools.context_query.load_models_config",
                return_value=mock_models_config,
            ),
            patch(
                "context_service.mcp.tools.context_query.LiteLLMReranker",
            ) as mock_reranker_cls,
        ):
            mock_reranker_cls.return_value.rerank = AsyncMock(return_value=reranked)

            from context_service.mcp.tools.context_query import _apply_reranking

            output, fallback_used, reranked_applied = await _apply_reranking(
                "query",
                mock_results,
                mock_settings,
                query_embedding=[0.1, 0.2],
                silo_id="silo-1",
                rerank_cache=mock_cache,
            )

        # Stale cache ignored; fresh rerank ran and wrote real scores.
        assert reranked_applied is True
        assert fallback_used is False
        score_map = {str(r.node_id): r.relevance_score for r in output}
        assert score_map["node-1"] == 0.91
        assert score_map["node-2"] == 0.50

    @pytest.mark.asyncio
    async def test_apply_reranking_fallback_keeps_cosine_scores(self) -> None:
        """When reranker raises, cosine scores are preserved, reranked_applied=False."""
        mock_results = [
            MagicMock(node_id="node-1", content="First", relevance_score=0.34),
            MagicMock(node_id="node-2", content="Second", relevance_score=0.80),
        ]
        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.reranking.reranker_timeout_seconds = 2.0
        mock_settings.vertex_project = None

        mock_models_config = MagicMock()
        mock_models_config.litellm_reranker_model = "test-model"

        with (
            patch(
                "context_service.mcp.tools.context_query.load_models_config",
                return_value=mock_models_config,
            ),
            patch(
                "context_service.mcp.tools.context_query.LiteLLMReranker",
            ) as mock_reranker_cls,
        ):
            mock_reranker_cls.return_value.rerank = AsyncMock(
                side_effect=RuntimeError("reranker unavailable")
            )

            from context_service.mcp.tools.context_query import _apply_reranking

            output, fallback_used, reranked_applied = await _apply_reranking(
                "query", mock_results, mock_settings
            )

        assert fallback_used is True
        assert reranked_applied is False
        # Cosine scores must be untouched
        score_map = {str(r.node_id): r.relevance_score for r in output}
        assert score_map["node-1"] == 0.34
        assert score_map["node-2"] == 0.80

    @pytest.mark.asyncio
    async def test_end_to_end_per_layer_floors_applied(self) -> None:
        """Integration: per-layer score floors are applied to FusionRetriever results.

        A knowledge-layer result with rrf_score 0.30 is dropped by the
        knowledge floor (0.35). FR handles reranking internally, so there
        is no separate fallback path -- per-layer floors always apply.
        """
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        # Two knowledge-layer results from FR:
        # node-1: rrf_score 0.30 -> below knowledge floor 0.35
        # node-2: rrf_score 0.80 -> above floor
        fused_results = [
            _FakeFusedResult(
                node_id="00000000-0000-0000-0000-000000000001",
                rrf_score=0.30,
                layer="knowledge",
                content="Borderline result",
                confidence=0.7,
                conflict_status="none",
            ),
            _FakeFusedResult(
                node_id="00000000-0000-0000-0000-000000000002",
                rrf_score=0.80,
                layer="knowledge",
                content="Strong result",
                confidence=0.9,
                conflict_status="none",
            ),
        ]

        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.reranking.adaptive_threshold_enabled = False
        mock_settings.causal = MagicMock()
        mock_settings.causal.query_enabled = False
        mock_settings.epistemic_fusion.enabled = False

        mock_silo = MagicMock()
        mock_silo.metadata = {}
        mock_silo_service = MagicMock()
        mock_silo_service.get_by_id = AsyncMock(return_value=mock_silo)

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                return_value=mock_auth,
            ),
            patch("context_service.mcp.tools.context_query.get_context_service"),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=mock_silo_service,
            ),
            patch(
                "context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None
            ),
            patch(
                "context_service.mcp.tools.context_query.get_settings", return_value=mock_settings
            ),
            patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
            patch(
                "context_service.mcp.tools.context_query.FusionRetriever"
            ) as mock_fr_cls,
        ):
            mock_fr_cls.return_value.retrieve = AsyncMock(return_value=fused_results)

            from context_service.mcp.tools.context_query import _context_query

            result = await _context_query(
                silo_id="test-silo",
                query="find something",
                top_k=10,
            )

        assert "results" in result
        # node-1 (rrf_score 0.30 < knowledge floor 0.35) must be dropped
        result_ids = [r["node_id"] for r in result["results"]]
        assert "00000000-0000-0000-0000-000000000001" not in result_ids, (
            "node-1 with rrf_score 0.30 should be filtered by per-layer knowledge floor 0.35"
        )
        assert "00000000-0000-0000-0000-000000000002" in result_ids
