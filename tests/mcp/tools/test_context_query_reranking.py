"""Tests for context_query reranking integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.reranker import RerankResult


class TestContextQueryReranking:
    @pytest.mark.asyncio
    async def test_query_with_reranking_enabled(self) -> None:
        """Test that reranking is applied when enabled."""
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        mock_results = [
            MagicMock(
                node_id="node-1",
                layer="memory",
                content="First result",
                summary=None,
                confidence=0.9,
                relevance_score=0.8,
                tags=[],
                created_at=None,
            ),
            MagicMock(
                node_id="node-2",
                layer="memory",
                content="Second result - no longer viable",
                summary=None,
                confidence=0.85,
                relevance_score=0.7,
                tags=[],
                created_at=None,
            ),
        ]

        mock_settings = MagicMock()
        mock_settings.reranking.enabled = True
        mock_settings.causal = MagicMock()
        mock_settings.causal.query_enabled = False

        mock_silo = MagicMock()
        mock_silo.freshness_decay_lambda = 0.01
        mock_silo.default_recall_threshold = 0.5
        mock_silo_service = MagicMock()
        mock_silo_service.get_by_id = AsyncMock(return_value=mock_silo)

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                return_value=mock_auth,
            ),
            patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
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
        ):
            mock_svc.return_value.query = AsyncMock(return_value=mock_results)

            from context_service.mcp.tools.context_query import _context_query

            result = await _context_query(
                silo_id="test-silo",
                query="what was rejected?",
                top_k=10,
            )

            assert "results" in result
            mock_svc.return_value.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_with_reranking_disabled(self) -> None:
        """Test that results are returned unchanged when reranking is disabled."""
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        mock_results = [
            MagicMock(
                node_id="node-1",
                layer="memory",
                content="First result",
                summary=None,
                confidence=0.9,
                relevance_score=0.8,
                tags=[],
                created_at=None,
            ),
        ]

        mock_settings = MagicMock()
        mock_settings.reranking.enabled = False
        mock_settings.causal = MagicMock()
        mock_settings.causal.query_enabled = False

        mock_silo = MagicMock()
        mock_silo.freshness_decay_lambda = 0.01
        mock_silo.default_recall_threshold = 0.5
        mock_silo_service = MagicMock()
        mock_silo_service.get_by_id = AsyncMock(return_value=mock_silo)

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                return_value=mock_auth,
            ),
            patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
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
        ):
            mock_svc.return_value.query = AsyncMock(return_value=mock_results)

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
