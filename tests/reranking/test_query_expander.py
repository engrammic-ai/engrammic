"""Tests for QueryExpander."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.query_expander import QueryExpander


class TestQueryExpander:
    @pytest.mark.asyncio
    async def test_expand_returns_expanded_query(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"expanded": "rejected OR denied OR dismissed OR \'no longer viable\'"}'
                )
            )
        ]

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
            )
            result = await expander.expand("what was rejected?")

            assert "rejected" in result
            assert "denied" in result
            assert "no longer viable" in result

    @pytest.mark.asyncio
    async def test_expand_returns_cached_result(self) -> None:
        cached_expansion = "rejected OR denied OR 'no longer viable'"
        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_expansion.encode()

        expander = QueryExpander(
            llm_model="vertex/gemini-2.5-flash",
            redis=mock_redis,
        )
        result = await expander.expand("what was rejected?")

        assert result == cached_expansion
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_expand_caches_new_expansion(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"expanded": "test expansion"}'))
        ]

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
                cache_ttl_seconds=86400,
            )
            await expander.expand("test query")

            mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_expand_fallback_on_error(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("LLM error"))

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
            )
            result = await expander.expand("test query")

            # Fallback: returns original query
            assert result == "test query"

    @pytest.mark.asyncio
    async def test_expand_fallback_on_malformed_json(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="not valid json"))
        ]

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
            )
            result = await expander.expand("test query")

            # Fallback: returns original query
            assert result == "test query"
