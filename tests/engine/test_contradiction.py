"""Tests for inline contradiction candidate flagging."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine.contradiction import (
    check_contradiction_candidates,
    clear_contradiction_flags,
    flag_contradiction_candidate,
    maybe_flag_contradiction,
)


class TestCheckContradictionCandidates:
    """Tests for the contradiction candidate check using Qdrant."""

    @pytest.mark.asyncio
    async def test_returns_candidates_above_threshold(self) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()

        # Mock Qdrant search results
        hit1 = MagicMock()
        hit1.payload = {"node_id": "node-1"}
        hit1.score = 0.95

        hit2 = MagicMock()
        hit2.payload = {"node_id": "node-2"}
        hit2.score = 0.90

        qdrant.search.return_value = [hit1, hit2]

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            qdrant_client=qdrant,
            threshold=0.85,
        )

        assert "node-1" in candidates
        assert "node-2" in candidates
        qdrant.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_qdrant_client(self) -> None:
        store = AsyncMock()

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            qdrant_client=None,
            threshold=0.85,
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_embedding(self) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[],
            qdrant_client=qdrant,
            threshold=0.85,
        )

        assert candidates == []
        qdrant.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_search_failure(self) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()
        qdrant.search.side_effect = Exception("Qdrant error")

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            qdrant_client=qdrant,
            threshold=0.85,
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_excludes_self_from_results(self) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()

        # Mock result that includes self (should be filtered by Qdrant query, but test the fallback)
        hit1 = MagicMock()
        hit1.payload = {"node_id": "new-node"}  # Same as query node
        hit1.score = 1.0

        hit2 = MagicMock()
        hit2.payload = {"node_id": "other-node"}
        hit2.score = 0.9

        qdrant.search.return_value = [hit1, hit2]

        candidates = await check_contradiction_candidates(
            store=store,
            silo_id="test-silo",
            node_id="new-node",
            embedding=[1.0, 0.0, 0.0],
            qdrant_client=qdrant,
            threshold=0.85,
        )

        assert "new-node" not in candidates
        assert "other-node" in candidates


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

    @pytest.mark.asyncio
    async def test_handles_failure(self) -> None:
        store = AsyncMock()
        store.execute_write.side_effect = Exception("DB error")

        result = await clear_contradiction_flags(
            store=store,
            silo_id="test-silo",
            node_id="node-1",
        )

        assert result is False


class TestMaybeFlagContradiction:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_flags_when_candidates_found(self) -> None:
        store = AsyncMock()
        store.execute_write.return_value = [{"id": "node-1"}]
        qdrant = AsyncMock()

        hit = MagicMock()
        hit.payload = {"node_id": "candidate-1"}
        hit.score = 0.95
        qdrant.search.return_value = [hit]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.contradiction.get_settings",
                lambda: MagicMock(
                    contradiction_flagging_enabled=True,
                    contradiction_candidate_threshold=0.85,
                ),
            )

            candidates = await maybe_flag_contradiction(
                store=store,
                silo_id="test-silo",
                node_id="new-node",
                embedding=[1.0, 0.0, 0.0],
                qdrant_client=qdrant,
            )

        assert candidates == ["candidate-1"]
        store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.contradiction.get_settings",
                lambda: MagicMock(contradiction_flagging_enabled=False),
            )

            candidates = await maybe_flag_contradiction(
                store=store,
                silo_id="test-silo",
                node_id="new-node",
                embedding=[1.0, 0.0, 0.0],
                qdrant_client=qdrant,
            )

        assert candidates == []
        qdrant.search.assert_not_called()
