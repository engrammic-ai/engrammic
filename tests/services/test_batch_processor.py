"""Tests for batch processor helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.services.batch_processor import BatchResult, batch_embed, dedup_check


@pytest.fixture
def mock_embedding_service():
    svc = AsyncMock()
    svc.embed = AsyncMock(side_effect=lambda texts: [[0.1] * 3] * len(texts))
    return svc


@pytest.fixture
def mock_graph_store():
    store = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_batch_embed_chunks_at_64(mock_embedding_service):
    texts = ["text"] * 100
    results = await batch_embed(texts, mock_embedding_service)
    assert len(results) == 100
    assert mock_embedding_service.embed.call_count == 2  # 64 + 36


@pytest.mark.asyncio
async def test_batch_embed_returns_none_on_failure(mock_embedding_service):
    mock_embedding_service.embed.side_effect = RuntimeError("embedding failed")
    texts = ["a", "b"]
    results = await batch_embed(texts, mock_embedding_service)
    assert results == [None, None]


@pytest.mark.asyncio
async def test_batch_embed_empty(mock_embedding_service):
    results = await batch_embed([], mock_embedding_service)
    assert results == []
    mock_embedding_service.embed.assert_not_called()


@pytest.mark.asyncio
async def test_batch_embed_respects_chunk_size(mock_embedding_service):
    texts = ["x"] * 10
    await batch_embed(texts, mock_embedding_service, chunk_size=3)
    # 10 items / 3 per chunk = ceil(10/3) = 4 calls
    assert mock_embedding_service.embed.call_count == 4


@pytest.mark.asyncio
async def test_dedup_check_returns_existing_ids(mock_graph_store):
    mock_graph_store.query_document_ids.return_value = {"doc1": "node-abc"}

    existing = await dedup_check(["doc1", "doc2", "doc3"], "silo-1", mock_graph_store)

    assert existing == {"doc1": "node-abc"}


@pytest.mark.asyncio
async def test_dedup_check_empty_input(mock_graph_store):
    result = await dedup_check([], "silo-1", mock_graph_store)
    assert result == {}
    mock_graph_store.query_document_ids.assert_not_called()


def test_batch_result_defaults():
    r = BatchResult()
    assert r.created == 0
    assert r.skipped == 0
    assert r.failed == 0
    assert r.results == []
