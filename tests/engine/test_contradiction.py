"""Tests for inline contradiction candidate flagging."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.engine.contradiction import (
    _cosine_similarity,
    check_contradiction_candidates,
    clear_contradiction_flags,
    flag_contradiction_candidate,
    maybe_flag_contradiction,
)


class TestCosineSimilarity:
    """Tests for the cosine similarity helper."""

    def test_identical_vectors(self) -> None:
        vec = [1.0, 2.0, 3.0]
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors(self) -> None:
        assert _cosine_similarity([], []) == 0.0

    def test_zero_vector(self) -> None:
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0


class TestCheckContradictionCandidates:
    """Tests for the contradiction candidate check."""

    @pytest.mark.asyncio
    async def test_returns_candidates_above_threshold(self) -> None:
        store = AsyncMock()
        store.execute_query.return_value = [
            {"id": "node-1", "content": "test", "embedding": [1.0, 0.0, 0.0]},
            {"id": "node-2", "content": "test", "embedding": [0.9, 0.1, 0.0]},
            {"id": "node-3", "content": "test", "embedding": [0.0, 1.0, 0.0]},
        ]

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            threshold=0.85,
        )

        assert "node-1" in candidates
        assert "node-2" in candidates
        assert "node-3" not in candidates

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_matches(self) -> None:
        store = AsyncMock()
        store.execute_query.return_value = [
            {"id": "node-1", "content": "test", "embedding": [0.0, 1.0, 0.0]},
        ]

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            threshold=0.85,
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_embedding(self) -> None:
        store = AsyncMock()

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[],
            threshold=0.85,
        )

        assert candidates == []
        store.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_query_failure(self) -> None:
        store = AsyncMock()
        store.execute_query.side_effect = Exception("DB error")

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            threshold=0.85,
        )

        assert candidates == []


class TestFlagContradictionCandidate:
    """Tests for the flagging function."""

    @pytest.mark.asyncio
    async def test_sets_flags(self) -> None:
        store = AsyncMock()
        store.execute_write.return_value = [{"id": "node-1"}]

        result = await flag_contradiction_candidate(
            store=store,
            silo_id="test-silo",
            node_id="node-1",
            candidate_ids=["node-2", "node-3"],
        )

        assert result is True
        store.execute_write.assert_called_once()
        call_args = store.execute_write.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["node_id"] == "node-1"
        assert params["candidate_ids"] == ["node-2", "node-3"]

    @pytest.mark.asyncio
    async def test_returns_false_for_empty_candidates(self) -> None:
        store = AsyncMock()

        result = await flag_contradiction_candidate(
            store=store,
            silo_id="test-silo",
            node_id="node-1",
            candidate_ids=[],
        )

        assert result is False
        store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_write_failure(self) -> None:
        store = AsyncMock()
        store.execute_write.side_effect = Exception("DB error")

        result = await flag_contradiction_candidate(
            store=store,
            silo_id="test-silo",
            node_id="node-1",
            candidate_ids=["node-2"],
        )

        assert result is False


class TestClearContradictionFlags:
    """Tests for clearing flags."""

    @pytest.mark.asyncio
    async def test_clears_flags(self) -> None:
        store = AsyncMock()
        store.execute_write.return_value = [{"id": "node-1"}]

        result = await clear_contradiction_flags(
            store=store,
            silo_id="test-silo",
            node_id="node-1",
        )

        assert result is True
        store.execute_write.assert_called_once()


class TestMaybeFlagContradiction:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_checks_and_flags(self) -> None:
        store = AsyncMock()
        store.execute_query.return_value = [
            {"id": "node-1", "content": "test", "embedding": [1.0, 0.0, 0.0]},
        ]
        store.execute_write.return_value = [{"id": "new-node"}]

        with patch("context_service.engine.contradiction.get_settings") as mock_settings:
            mock_settings.return_value.contradiction_flagging_enabled = True
            mock_settings.return_value.contradiction_candidate_threshold = 0.85

            candidates = await maybe_flag_contradiction(
                store=store,
                silo_id="test-silo",
                node_id="new-node",
                embedding=[1.0, 0.0, 0.0],
            )

        assert "node-1" in candidates
        store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_disabled_flag(self) -> None:
        store = AsyncMock()

        with patch("context_service.engine.contradiction.get_settings") as mock_settings:
            mock_settings.return_value.contradiction_flagging_enabled = False

            candidates = await maybe_flag_contradiction(
                store=store,
                silo_id="test-silo",
                node_id="new-node",
                embedding=[1.0, 0.0, 0.0],
            )

        assert candidates == []
        store.execute_query.assert_not_called()
