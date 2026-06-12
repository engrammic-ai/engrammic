"""Unit tests for BM25 retrieval channel."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from context_service.retrieval.fusion import ChannelResult, FusionRetriever


def _make_row(node_id: str, rank: float = 0.5) -> MagicMock:
    """Build a mock asyncpg Record-like object."""
    row = MagicMock()
    row.__getitem__ = lambda _self, key: node_id if key == "id" else rank
    return row


def _mock_pool(rows: list) -> MagicMock:
    """Build a mock asyncpg pool that returns given rows from conn.fetch."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class TestBM25Channel:
    @pytest.mark.asyncio
    async def test_bm25_returns_channel_result(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        pool = _mock_pool([])
        with patch("context_service.retrieval.fusion.get_db_pool", return_value=pool):
            result = await fusion_retriever._bm25_channel(
                query="test query",
                scope=scope_context,
                top_k=10,
                layers=None,
            )
        assert isinstance(result, ChannelResult)
        assert result.channel_name == "bm25"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_bm25_empty_query_returns_empty(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        result = await fusion_retriever._bm25_channel(
            query="",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert result.ranked_ids == []
        assert result.error is None

    @pytest.mark.asyncio
    async def test_bm25_whitespace_query_returns_empty(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        result = await fusion_retriever._bm25_channel(
            query="   ",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert result.ranked_ids == []

    @pytest.mark.asyncio
    async def test_bm25_returns_ranked_ids(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        node_a = str(uuid4())
        node_b = str(uuid4())
        rows = [_make_row(node_a, 0.9), _make_row(node_b, 0.5)]
        pool = _mock_pool(rows)

        with patch("context_service.retrieval.fusion.get_db_pool", return_value=pool):
            result = await fusion_retriever._bm25_channel(
                query="exact phrase test",
                scope=scope_context,
                top_k=10,
                layers=None,
            )

        assert result.ranked_ids == [node_a, node_b]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_bm25_respects_layers_filter(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        pool = _mock_pool([])
        with patch(
            "context_service.retrieval.fusion.get_db_pool", return_value=pool
        ) as _mock_pool_fn:
            result = await fusion_retriever._bm25_channel(
                query="test",
                scope=scope_context,
                top_k=10,
                layers=["memory"],
            )

        assert isinstance(result, ChannelResult)
        assert result.channel_name == "bm25"
        # Verify that the pool was called (layers path taken)
        pool.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_bm25_no_pool_returns_error(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        with patch("context_service.retrieval.fusion.get_db_pool", return_value=None):
            result = await fusion_retriever._bm25_channel(
                query="test query",
                scope=scope_context,
                top_k=10,
                layers=None,
            )
        assert result.ranked_ids == []
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_bm25_db_error_returns_error_result(
        self, fusion_retriever: FusionRetriever, scope_context: MagicMock
    ) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=RuntimeError("db gone"))
        pool = MagicMock()
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("context_service.retrieval.fusion.get_db_pool", return_value=pool):
            result = await fusion_retriever._bm25_channel(
                query="test",
                scope=scope_context,
                top_k=10,
                layers=None,
            )

        assert result.ranked_ids == []
        assert result.error is not None
        assert "db gone" in result.error
