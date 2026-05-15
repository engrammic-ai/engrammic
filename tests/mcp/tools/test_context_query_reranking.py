"""Tests for context_query reranking integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

        with (
            patch("context_service.mcp.tools.context_query.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
            patch("context_service.mcp.tools.context_query.get_silo_service"),
            patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
            patch("context_service.mcp.tools.context_query.get_settings", return_value=mock_settings),
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

        with (
            patch("context_service.mcp.tools.context_query.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
            patch("context_service.mcp.tools.context_query.get_silo_service"),
            patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
            patch("context_service.mcp.tools.context_query.get_settings", return_value=mock_settings),
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

        output = await _apply_reranking("query", [mock_result], mock_settings)
        assert output == [mock_result]

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

        with patch("context_service.mcp.tools.context_query.load_models_config", return_value=mock_models_config):
            from context_service.mcp.tools.context_query import _apply_reranking

            output = await _apply_reranking("query", mock_results, mock_settings)
            assert output == mock_results
