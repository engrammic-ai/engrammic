"""Tests for AutoTaggingService."""

import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest

from context_service.services.auto_tagging import AutoTaggingService, VocabCache


class TestVocabCache:
    def test_match_returns_matching_tags(self):
        tags = ["database", "api", "frontend"]
        vectors = np.array(
            [
                [1.0, 0.0, 0.0],  # database
                [0.0, 1.0, 0.0],  # api
                [0.0, 0.0, 1.0],  # frontend
            ],
            dtype=np.float32,
        )

        cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
        query = np.array([0.9, 0.1, 0.0], dtype=np.float32)

        matches = cache.match(query, threshold=0.4, max_tags=5)

        assert "database" in matches
        assert len(matches) <= 5

    def test_match_respects_threshold(self):
        tags = ["tag1", "tag2"]
        vectors = np.array(
            [
                [1.0, 0.0],
                [0.0, 1.0],
            ],
            dtype=np.float32,
        )

        cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
        query = np.array([1.0, 0.0], dtype=np.float32)

        # High threshold - only exact match
        matches = cache.match(query, threshold=0.99, max_tags=5)
        assert matches == ["tag1"]

        # Low threshold - only tag1 matches (tag2 has similarity 0)
        matches = cache.match(query, threshold=-0.1, max_tags=5)
        assert len(matches) == 2

    def test_match_respects_max_tags(self):
        tags = ["t1", "t2", "t3", "t4", "t5"]
        vectors = np.eye(5, dtype=np.float32)

        cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
        query = np.ones(5, dtype=np.float32)

        matches = cache.match(query, threshold=0.0, max_tags=2)
        assert len(matches) == 2

    def test_match_empty_tags(self):
        cache = VocabCache(tags=[], matrix=np.array([]), loaded_at=0.0)
        query = np.array([1.0, 0.0], dtype=np.float32)

        matches = cache.match(query, threshold=0.0, max_tags=5)
        assert matches == []

    def test_match_zero_norm_query(self):
        tags = ["tag1"]
        vectors = np.array([[1.0, 0.0]], dtype=np.float32)
        cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)

        query = np.array([0.0, 0.0], dtype=np.float32)
        matches = cache.match(query, threshold=0.0, max_tags=5)
        assert matches == []


class TestAutoTaggingService:
    @pytest.fixture
    def mock_embedding(self):
        service = AsyncMock()
        service.embed = AsyncMock(
            return_value=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        return service

    @pytest.fixture
    def mock_tag_config(self):
        service = AsyncMock()
        service.get_all_tags = AsyncMock(return_value=["database", "api"])
        return service

    @pytest.mark.asyncio
    async def test_suggest_tags(self, mock_embedding, mock_tag_config):
        service = AutoTaggingService(
            embedding=mock_embedding,
            tag_config=mock_tag_config,
        )

        silo_id = uuid.uuid4()
        content_vector = [0.9, 0.1, 0.0]

        tags = await service.suggest_tags(content_vector, str(silo_id))

        assert "database" in tags

    @pytest.mark.asyncio
    async def test_caches_vocabulary(self, mock_embedding, mock_tag_config):
        service = AutoTaggingService(
            embedding=mock_embedding,
            tag_config=mock_tag_config,
        )

        silo_id = str(uuid.uuid4())
        content_vector = [1.0, 0.0, 0.0]

        # First call loads vocabulary
        await service.suggest_tags(content_vector, silo_id)
        # Second call uses cache
        await service.suggest_tags(content_vector, silo_id)

        # embed called only once (cached)
        assert mock_embedding.embed.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_vocabulary(self, mock_embedding, mock_tag_config):
        mock_tag_config.get_all_tags.return_value = []

        service = AutoTaggingService(
            embedding=mock_embedding,
            tag_config=mock_tag_config,
        )

        tags = await service.suggest_tags([1.0, 0.0], str(uuid.uuid4()))
        assert tags == []

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self, mock_embedding, mock_tag_config):
        service = AutoTaggingService(
            embedding=mock_embedding,
            tag_config=mock_tag_config,
        )

        silo_id = str(uuid.uuid4())
        await service.suggest_tags([1.0, 0.0, 0.0], silo_id)
        service.invalidate(silo_id)
        await service.suggest_tags([1.0, 0.0, 0.0], silo_id)

        # embed called twice after invalidation
        assert mock_embedding.embed.call_count == 2
