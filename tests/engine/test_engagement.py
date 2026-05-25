"""Tests for engine/engagement.py -- engagement detection for recall responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture
def mock_redis_with_touches():
    """Mock redis that supports record_touch pipeline calls (zadd/zremrangebyscore/zrangebyscore)."""
    redis = AsyncMock()

    pipe = AsyncMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zrangebyscore = MagicMock(return_value=pipe)
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    # Default: first pipeline call (get_markers_for_about_set) returns empty,
    # subsequent calls (record_touch) return count=0 (below threshold).
    pipe.execute = AsyncMock(return_value=[1, 0, []])

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

    @pytest.mark.asyncio
    async def test_below_threshold_stays_soft(self, mock_store, mock_redis_with_touches):
        """Touch count below threshold keeps mode soft."""
        call_count = 0

        async def side_effect() -> list[object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_markers_for_about_set pipeline: one zrange result per about_id
                return [[b"marker-1"]]
            # record_touch pipeline: [zadd_result, zremrangebyscore_result, members]
            # count = 1 (one member with session prefix, below threshold of 3)
            return [1, 0, [b"sess-1:12345678"]]

        mock_redis_with_touches._mock_pipe.execute = AsyncMock(side_effect=side_effect)
        mock_store.execute_query.side_effect = [
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
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        with patch("context_service.engine.engagement.get_settings") as mock_settings:
            settings = MagicMock()
            settings.engagement_escalation_threshold = 3
            settings.engagement_decay_window_ms = 1_800_000
            settings.engagement_hard_enabled = True
            mock_settings.return_value = settings

            result = await get_engagement_for_about_set(
                redis=mock_redis_with_touches,
                store=mock_store,
                silo_id="silo-1",
                about_ids=["node-a"],
                session_id="sess-1",
            )

        assert result is not None
        assert result["mode"] == "soft"
        assert "message" not in result

    @pytest.mark.asyncio
    async def test_at_threshold_escalates_to_hard(self, mock_store, mock_redis_with_touches):
        """Touch count at threshold with hard enabled escalates to hard mode."""
        call_count = 0

        async def side_effect() -> list[object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[b"marker-1"]]
            # record_touch: count = 3 (at threshold of 3)
            return [1, 0, [b"sess-1:1", b"sess-1:2", b"sess-1:3"]]

        mock_redis_with_touches._mock_pipe.execute = AsyncMock(side_effect=side_effect)
        mock_store.execute_query.side_effect = [
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
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        with patch("context_service.engine.engagement.get_settings") as mock_settings:
            settings = MagicMock()
            settings.engagement_escalation_threshold = 3
            settings.engagement_decay_window_ms = 1_800_000
            settings.engagement_hard_enabled = True
            mock_settings.return_value = settings

            result = await get_engagement_for_about_set(
                redis=mock_redis_with_touches,
                store=mock_store,
                silo_id="silo-1",
                about_ids=["node-a"],
                session_id="sess-1",
            )

        assert result is not None
        assert result["mode"] == "hard"
        assert "message" in result
        assert "Resolution required" in result["message"]

    @pytest.mark.asyncio
    async def test_above_threshold_escalates_to_hard(self, mock_store, mock_redis_with_touches):
        """Touch count above threshold with hard enabled escalates to hard mode."""
        call_count = 0

        async def side_effect() -> list[object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[b"marker-1"]]
            # record_touch: count = 5 (above threshold of 3)
            return [1, 0, [b"sess-1:1", b"sess-1:2", b"sess-1:3", b"sess-1:4", b"sess-1:5"]]

        mock_redis_with_touches._mock_pipe.execute = AsyncMock(side_effect=side_effect)
        mock_store.execute_query.side_effect = [
            [
                {
                    "id": "marker-1",
                    "marker_type": "StaleCommitment",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["commit-1"],
                    "commitment_id": "commit-1",
                }
            ],
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        with patch("context_service.engine.engagement.get_settings") as mock_settings:
            settings = MagicMock()
            settings.engagement_escalation_threshold = 3
            settings.engagement_decay_window_ms = 1_800_000
            settings.engagement_hard_enabled = True
            mock_settings.return_value = settings

            result = await get_engagement_for_about_set(
                redis=mock_redis_with_touches,
                store=mock_store,
                silo_id="silo-1",
                about_ids=["commit-1"],
                session_id="sess-1",
            )

        assert result is not None
        assert result["mode"] == "hard"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_hard_disabled_stays_soft_despite_threshold(self, mock_store, mock_redis_with_touches):
        """When engagement_hard_enabled is False, stays soft even above threshold."""
        call_count = 0

        async def side_effect() -> list[object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[b"marker-1"]]
            # record_touch: count = 5 (above threshold)
            return [1, 0, [b"sess-1:1", b"sess-1:2", b"sess-1:3", b"sess-1:4", b"sess-1:5"]]

        mock_redis_with_touches._mock_pipe.execute = AsyncMock(side_effect=side_effect)
        mock_store.execute_query.side_effect = [
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
            [],
        ]

        from context_service.engine.engagement import get_engagement_for_about_set

        with patch("context_service.engine.engagement.get_settings") as mock_settings:
            settings = MagicMock()
            settings.engagement_escalation_threshold = 3
            settings.engagement_decay_window_ms = 1_800_000
            settings.engagement_hard_enabled = False
            mock_settings.return_value = settings

            result = await get_engagement_for_about_set(
                redis=mock_redis_with_touches,
                store=mock_store,
                silo_id="silo-1",
                about_ids=["node-a"],
                session_id="sess-1",
            )

        assert result is not None
        assert result["mode"] == "soft"
        assert "message" not in result


# ---------------------------------------------------------------------------
# get_engagement_for_silo
# ---------------------------------------------------------------------------


class TestGetEngagementForSilo:
    @pytest.mark.asyncio
    async def test_no_markers_no_proposed_beliefs_returns_none(
        self, mock_store, mock_redis
    ):
        mock_store.execute_query.return_value = []

        from context_service.engine.engagement import get_engagement_for_silo

        result = await get_engagement_for_silo(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_proposed_belief_included_when_no_other_markers(
        self, mock_store, mock_redis
    ):
        """ProposedBelief should appear in no-hint silo engagement."""
        mock_store.execute_query.side_effect = [
            # get_all_pending_markers returns nothing
            [],
            # GET_PROPOSED_BELIEFS_FOR_SILO returns one pending belief
            [
                {
                    "proposed_belief_id": "pb-silo-1",
                    "content": "Users prefer dark mode by default",
                    "confidence": 0.9,
                    "created_at": "2026-05-25T12:00:00+00:00",
                    "source_fact_ids": ["fact-a", "fact-b"],
                }
            ],
        ]

        from context_service.engine.engagement import get_engagement_for_silo

        result = await get_engagement_for_silo(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
        )

        assert result is not None
        assert result["mode"] == "soft"
        assert len(result["markers"]) == 1
        m = result["markers"][0]
        assert m["marker_id"] == "pb-silo-1"
        assert m["marker_type"] == "ProposedBelief"
        assert "dark mode" in m["summary"]
        assert m["decision_required"] == "accept"
        assert m["node_ids"] == ["fact-a", "fact-b"]

    @pytest.mark.asyncio
    async def test_includes_both_markers_and_proposed_beliefs(
        self, mock_store, mock_redis
    ):
        """Both Contradiction markers and ProposedBeliefs must appear in result."""
        mock_store.execute_query.side_effect = [
            # get_all_pending_markers returns one marker ID
            [{"id": "marker-c1"}],
            # get_marker_details returns the full marker
            [
                {
                    "id": "marker-c1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a", "node-b"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                }
            ],
            # GET_PROPOSED_BELIEFS_FOR_SILO
            [
                {
                    "proposed_belief_id": "pb-s1",
                    "content": "A system belief",
                    "confidence": 0.8,
                    "created_at": "2026-05-25T11:00:00+00:00",
                    "source_fact_ids": ["fact-1"],
                }
            ],
        ]

        from context_service.engine.engagement import get_engagement_for_silo

        result = await get_engagement_for_silo(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
        )

        assert result is not None
        assert len(result["markers"]) == 2
        types = {m["marker_type"] for m in result["markers"]}
        assert types == {"Contradiction", "ProposedBelief"}

    @pytest.mark.asyncio
    async def test_proposed_belief_query_failure_graceful(
        self, mock_store, mock_redis
    ):
        """Failure in ProposedBelief query should not break marker results."""
        mock_store.execute_query.side_effect = [
            # get_all_pending_markers returns one marker ID
            [{"id": "marker-c1"}],
            # get_marker_details returns the full marker
            [
                {
                    "id": "marker-c1",
                    "marker_type": "Contradiction",
                    "status": "pending",
                    "detected_at": "2026-05-25T10:00:00+00:00",
                    "about_ids": ["node-a", "node-b"],
                    "node_a_id": "node-a",
                    "node_b_id": "node-b",
                }
            ],
            # GET_PROPOSED_BELIEFS_FOR_SILO fails
            Exception("DB error"),
        ]

        from context_service.engine.engagement import get_engagement_for_silo

        result = await get_engagement_for_silo(
            redis=mock_redis,
            store=mock_store,
            silo_id="silo-1",
        )

        assert result is not None
        assert len(result["markers"]) == 1
        assert result["markers"][0]["marker_type"] == "Contradiction"
