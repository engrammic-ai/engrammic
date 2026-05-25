"""Tests for engine/engagement.py -- engagement detection for recall responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_write = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_redis():
    """Mock redis.asyncio.Redis with pipeline support."""
    redis = AsyncMock()

    pipe = AsyncMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zrem = MagicMock(return_value=pipe)
    pipe.zrange = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])

    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)

    redis.pipeline = MagicMock(return_value=pipe)
    redis._mock_pipe = pipe
    return redis


# ---------------------------------------------------------------------------
# get_engagement_for_about_set
# ---------------------------------------------------------------------------


class TestGetEngagementForAboutSet:
    @pytest.mark.asyncio
    async def test_empty_about_ids_returns_none(self, mock_store, mock_redis):
        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=[],
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_markers_returns_none(self, mock_store, mock_redis):
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[]])
        mock_store.execute_query.return_value = []

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["node-a"],
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_single_contradiction_marker(self, mock_store, mock_redis):
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[b"marker-1"]])
        mock_store.execute_query.side_effect = [
            # get_marker_details call
            [
                {
                    "id": "marker-1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a", "node-b"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                }
            ],
            # GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["node-a"],
        )

        assert result is not None
        assert result["mode"] == "soft"
        assert len(result["markers"]) == 1
        marker = result["markers"][0]
        assert marker["marker_id"] == "marker-1"
        assert marker["marker_type"] == "Contradiction"
        assert "Contradiction between node-a and node-b" in marker["summary"]
        assert marker["decision_required"] == "dismiss"

    @pytest.mark.asyncio
    async def test_single_stale_commitment_marker(self, mock_store, mock_redis):
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[b"marker-2"]])
        mock_store.execute_query.side_effect = [
            # get_marker_details call
            [
                {
                    "id": "marker-2",
                    "marker_type": "StaleCommitment",
                    "status": "pending",
                    "detected_at": "2026-05-25T11:00:00+00:00",
                    "about_ids": ["commit-1"],
                    "commitment_id": "commit-1",
                }
            ],
            # GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["commit-1"],
        )

        assert result is not None
        assert len(result["markers"]) == 1
        marker = result["markers"][0]
        assert marker["marker_type"] == "StaleCommitment"
        assert "Commitment commit-1 may be stale" in marker["summary"]
        assert marker["decision_required"] == "dismiss"

    @pytest.mark.asyncio
    async def test_single_proposed_belief(self, mock_store, mock_redis):
        # No markers from Redis
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[]])
        # Only GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call (no get_marker_details since marker_ids is empty)
        mock_store.execute_query.return_value = [
            {
                "id": "pb-1",
                "content": "Users prefer dark mode by default",
                "confidence": 0.85,
                "status": "pending",
                "created_at": "2026-05-25T12:00:00+00:00",
                "about_ids": ["fact-1", "fact-2"],
            }
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["fact-1"],
        )

        assert result is not None
        assert len(result["markers"]) == 1
        marker = result["markers"][0]
        assert marker["marker_id"] == "pb-1"
        assert marker["marker_type"] == "ProposedBelief"
        assert "System synthesized belief:" in marker["summary"]
        assert "dark mode" in marker["summary"]
        assert marker["decision_required"] == "accept"

    @pytest.mark.asyncio
    async def test_mixed_marker_types(self, mock_store, mock_redis):
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[b"marker-1", b"marker-2"]])
        mock_store.execute_query.side_effect = [
            # get_marker_details call
            [
                {
                    "id": "marker-1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a", "node-b"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                },
                {
                    "id": "marker-2",
                    "marker_type": "StaleCommitment",
                    "status": "pending",
                    "detected_at": "2026-05-25T11:00:00+00:00",
                    "about_ids": ["commit-1"],
                    "commitment_id": "commit-1",
                },
            ],
            # GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call
            [
                {
                    "id": "pb-1",
                    "content": "A synthesized belief",
                    "status": "pending",
                    "created_at": "2026-05-25T12:00:00+00:00",
                    "about_ids": ["fact-1"],
                }
            ],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["node-a", "commit-1", "fact-1"],
        )

        assert result is not None
        assert len(result["markers"]) == 3
        types = {m["marker_type"] for m in result["markers"]}
        assert types == {"Contradiction", "StaleCommitment", "ProposedBelief"}

    @pytest.mark.asyncio
    async def test_filters_out_non_pending_markers(self, mock_store, mock_redis):
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[b"marker-1", b"marker-2"]])
        mock_store.execute_query.side_effect = [
            # get_marker_details call - one pending, one resolved
            [
                {
                    "id": "marker-1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                },
                {
                    "id": "marker-2",
                    "marker_type": "Contradiction",
                    "status": "resolved",
                    "detected_at": "2026-05-25T09:00:00+00:00",
                    "about_ids": ["node-a"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-c",
                },
            ],
            # GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call
            [
                {
                    "id": "pb-1",
                    "content": "Pending belief",
                    "status": "pending",
                    "created_at": "2026-05-25T12:00:00+00:00",
                    "about_ids": ["fact-1"],
                },
                {
                    "id": "pb-2",
                    "content": "Accepted belief",
                    "status": "accepted",
                    "created_at": "2026-05-25T11:00:00+00:00",
                    "about_ids": ["fact-2"],
                },
            ],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["node-a", "fact-1"],
        )

        assert result is not None
        assert len(result["markers"]) == 2
        marker_ids = {m["marker_id"] for m in result["markers"]}
        assert marker_ids == {"marker-1", "pb-1"}

    @pytest.mark.asyncio
    async def test_proposed_belief_query_failure_graceful(self, mock_store, mock_redis):
        """ProposedBelief query failure should not break the function."""
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[b"marker-1"]])
        mock_store.execute_query.side_effect = [
            # get_marker_details call
            [
                {
                    "id": "marker-1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a", "node-b"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                }
            ],
            # GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call fails
            Exception("Database connection lost"),
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["node-a"],
        )

        # Should still return the contradiction marker
        assert result is not None
        assert len(result["markers"]) == 1
        assert result["markers"][0]["marker_type"] == "Contradiction"

    @pytest.mark.asyncio
    async def test_long_content_truncated_in_summary(self, mock_store, mock_redis):
        long_content = "A" * 200
        # No markers from Redis
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[[]])
        # Only GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS call
        mock_store.execute_query.return_value = [
            {
                "id": "pb-1",
                "content": long_content,
                "status": "pending",
                "created_at": "2026-05-25T12:00:00+00:00",
                "about_ids": ["fact-1"],
            }
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        result = await get_engagement_for_about_set(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
            about_ids=["fact-1"],
        )

        assert result is not None
        marker = result["markers"][0]
        assert marker["summary"].endswith("...")
        # Summary should be truncated to ~80 chars of content
        assert len(marker["summary"]) < 150
