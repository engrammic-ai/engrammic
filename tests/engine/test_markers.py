"""Tests for engine/markers.py — marker helper functions with Redis index."""

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
    store.execute_query = AsyncMock()
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

    # pipeline() is a sync call that returns an async context manager
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)

    redis.pipeline = MagicMock(return_value=pipe)
    redis._mock_pipe = pipe
    return redis


# ---------------------------------------------------------------------------
# create_contradiction
# ---------------------------------------------------------------------------


class TestCreateContradiction:
    @pytest.mark.asyncio
    async def test_creates_marker_and_returns_dict(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "some-id"}]

        from context_service.engine.markers import create_contradiction

        result = await create_contradiction(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            node_a_id="node-a",
            node_b_id="node-b",
            about_ids=["node-a", "node-b"],
            confidence=0.9,
        )

        assert result["marker_type"] == "Contradiction"
        assert result["status"] == "pending"
        assert result["silo_id"] == "silo-1"
        assert result["node_a_id"] == "node-a"
        assert result["node_b_id"] == "node-b"
        assert result["confidence"] == 0.9
        assert "marker_id" in result
        assert "detected_at" in result
        assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_calls_execute_write_with_correct_params(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "x"}]

        from context_service.engine.markers import create_contradiction

        await create_contradiction(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            node_a_id="node-a",
            node_b_id="node-b",
            about_ids=["node-a", "node-b"],
            confidence=0.8,
        )

        call_args = mock_store.execute_write.call_args
        params = call_args[0][1]
        assert params["silo_id"] == "silo-1"
        assert params["node_a_id"] == "node-a"
        assert params["node_b_id"] == "node-b"
        assert params["about_ids"] == ["node-a", "node-b"]
        assert params["confidence"] == 0.8
        assert "id" in params
        assert "detected_at" in params
        assert "expires_at" in params

    @pytest.mark.asyncio
    async def test_updates_redis_index_for_each_about_id(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "x"}]

        from context_service.engine.markers import create_contradiction

        await create_contradiction(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            node_a_id="node-a",
            node_b_id="node-b",
            about_ids=["node-a", "node-b"],
            confidence=0.75,
        )

        pipe = mock_redis._mock_pipe
        assert pipe.zadd.call_count == 2
        keys_called = [call[0][0] for call in pipe.zadd.call_args_list]
        assert "markers:silo-1:about:node-a" in keys_called
        assert "markers:silo-1:about:node-b" in keys_called

    @pytest.mark.asyncio
    async def test_raises_on_empty_write_result(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = []

        from context_service.engine.markers import create_contradiction

        with pytest.raises(RuntimeError, match="CREATE_CONTRADICTION"):
            await create_contradiction(
                store=mock_store,
                redis=mock_redis,
                silo_id="silo-1",
                node_a_id="node-a",
                node_b_id="node-b",
                about_ids=["node-a"],
                confidence=0.5,
            )

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "x"}]
        mock_redis._mock_pipe.execute = AsyncMock(side_effect=ConnectionError("down"))

        from context_service.engine.markers import create_contradiction

        # Should not raise even if Redis is unavailable
        result = await create_contradiction(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            node_a_id="node-a",
            node_b_id="node-b",
            about_ids=["node-a"],
            confidence=0.6,
        )
        assert result["marker_type"] == "Contradiction"


# ---------------------------------------------------------------------------
# create_stale_commitment
# ---------------------------------------------------------------------------


class TestCreateStaleCommitment:
    @pytest.mark.asyncio
    async def test_creates_marker_and_returns_dict(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "sc-1"}]

        from context_service.engine.markers import create_stale_commitment

        result = await create_stale_commitment(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            commitment_id="commit-1",
            evidence_ids=["ev-1", "ev-2"],
            about_ids=["commit-1", "ev-1"],
        )

        assert result["marker_type"] == "StaleCommitment"
        assert result["status"] == "pending"
        assert result["commitment_id"] == "commit-1"
        assert result["evidence_ids"] == ["ev-1", "ev-2"]
        assert "marker_id" in result

    @pytest.mark.asyncio
    async def test_calls_execute_write_with_correct_params(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "x"}]

        from context_service.engine.markers import create_stale_commitment

        await create_stale_commitment(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-2",
            commitment_id="commit-x",
            evidence_ids=["ev-x"],
            about_ids=["commit-x"],
        )

        params = mock_store.execute_write.call_args[0][1]
        assert params["silo_id"] == "silo-2"
        assert params["commitment_id"] == "commit-x"
        assert params["evidence_ids"] == ["ev-x"]

    @pytest.mark.asyncio
    async def test_raises_on_empty_write_result(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = []

        from context_service.engine.markers import create_stale_commitment

        with pytest.raises(RuntimeError, match="CREATE_STALE_COMMITMENT"):
            await create_stale_commitment(
                store=mock_store,
                redis=mock_redis,
                silo_id="silo-1",
                commitment_id="c",
                evidence_ids=[],
                about_ids=["c"],
            )

    @pytest.mark.asyncio
    async def test_updates_redis_index(self, mock_store, mock_redis):
        mock_store.execute_write.return_value = [{"marker_id": "x"}]

        from context_service.engine.markers import create_stale_commitment

        await create_stale_commitment(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            commitment_id="c1",
            evidence_ids=["e1"],
            about_ids=["c1", "e1"],
        )

        pipe = mock_redis._mock_pipe
        assert pipe.zadd.call_count == 2


# ---------------------------------------------------------------------------
# resolve_marker
# ---------------------------------------------------------------------------


class TestResolveMarker:
    @pytest.mark.asyncio
    async def test_resolves_marker_and_returns_dict(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [
            {"id": "m-1", "about_ids": ["node-a", "node-b"]}
        ]
        mock_store.execute_write.return_value = [
            {"marker_id": "m-1", "marker_type": "Contradiction"}
        ]

        from context_service.engine.markers import resolve_marker

        result = await resolve_marker(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            marker_id="m-1",
            resolution="superseded by newer claim",
        )

        assert result["marker_id"] == "m-1"
        assert result["marker_type"] == "Contradiction"
        assert result["status"] == "resolved"
        assert result["resolution"] == "superseded by newer claim"

    @pytest.mark.asyncio
    async def test_calls_update_with_resolved_status(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [{"about_ids": ["n1"]}]
        mock_store.execute_write.return_value = [
            {"marker_id": "m-1", "marker_type": "Contradiction"}
        ]

        from context_service.engine.markers import resolve_marker

        await resolve_marker(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            marker_id="m-1",
            resolution="done",
        )

        write_params = mock_store.execute_write.call_args[0][1]
        assert write_params["status"] == "resolved"
        assert write_params["resolution"] == "done"

    @pytest.mark.asyncio
    async def test_removes_from_redis_index(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [
            {"about_ids": ["node-a", "node-b"]}
        ]
        mock_store.execute_write.return_value = [
            {"marker_id": "m-1", "marker_type": "Contradiction"}
        ]

        from context_service.engine.markers import resolve_marker

        await resolve_marker(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            marker_id="m-1",
            resolution="done",
        )

        pipe = mock_redis._mock_pipe
        assert pipe.zrem.call_count == 2
        keys_called = [call[0][0] for call in pipe.zrem.call_args_list]
        assert "markers:silo-1:about:node-a" in keys_called
        assert "markers:silo-1:about:node-b" in keys_called

    @pytest.mark.asyncio
    async def test_raises_on_empty_update_result(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [{"about_ids": []}]
        mock_store.execute_write.return_value = []

        from context_service.engine.markers import resolve_marker

        with pytest.raises(RuntimeError, match="UPDATE_MARKER_STATUS"):
            await resolve_marker(
                store=mock_store,
                redis=mock_redis,
                silo_id="silo-1",
                marker_id="m-1",
                resolution="x",
            )


# ---------------------------------------------------------------------------
# dismiss_marker
# ---------------------------------------------------------------------------


class TestDismissMarker:
    @pytest.mark.asyncio
    async def test_dismisses_marker(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [
            {"about_ids": ["node-x"]}
        ]
        mock_store.execute_write.return_value = [
            {"marker_id": "m-2", "marker_type": "StaleCommitment"}
        ]

        from context_service.engine.markers import dismiss_marker

        result = await dismiss_marker(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            marker_id="m-2",
            reason="false positive",
        )

        assert result["status"] == "dismissed"
        assert result["resolution"] == "false positive"

    @pytest.mark.asyncio
    async def test_removes_from_redis_index(self, mock_store, mock_redis):
        mock_store.execute_query.return_value = [{"about_ids": ["node-x"]}]
        mock_store.execute_write.return_value = [
            {"marker_id": "m-2", "marker_type": "StaleCommitment"}
        ]

        from context_service.engine.markers import dismiss_marker

        await dismiss_marker(
            store=mock_store,
            redis=mock_redis,
            silo_id="silo-1",
            marker_id="m-2",
            reason="fp",
        )

        pipe = mock_redis._mock_pipe
        assert pipe.zrem.call_count == 1
        assert pipe.zrem.call_args[0][0] == "markers:silo-1:about:node-x"


# ---------------------------------------------------------------------------
# get_markers_for_about_set
# ---------------------------------------------------------------------------


class TestGetMarkersForAboutSet:
    @pytest.mark.asyncio
    async def test_returns_deduplicated_marker_ids(self, mock_redis):
        # Two about_ids share one marker, one has a unique marker
        pipe = mock_redis._mock_pipe
        pipe.execute = AsyncMock(return_value=[[b"m-1", b"m-2"], [b"m-1", b"m-3"]])

        from context_service.engine.markers import get_markers_for_about_set

        result = await get_markers_for_about_set(
            redis=mock_redis,
            silo_id="silo-1",
            about_ids=["node-a", "node-b"],
        )

        assert result == ["m-1", "m-2", "m-3"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_about_ids(self, mock_redis):
        from context_service.engine.markers import get_markers_for_about_set

        result = await get_markers_for_about_set(
            redis=mock_redis,
            silo_id="silo-1",
            about_ids=[],
        )

        assert result == []
        mock_redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_redis_failure(self, mock_redis):
        mock_redis.pipeline = MagicMock(side_effect=ConnectionError("down"))

        from context_service.engine.markers import get_markers_for_about_set

        result = await get_markers_for_about_set(
            redis=mock_redis,
            silo_id="silo-1",
            about_ids=["node-a"],
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_calls_zrange_for_each_about_id(self, mock_redis):
        pipe = mock_redis._mock_pipe
        pipe.execute = AsyncMock(return_value=[[], []])

        from context_service.engine.markers import get_markers_for_about_set

        await get_markers_for_about_set(
            redis=mock_redis,
            silo_id="silo-1",
            about_ids=["node-a", "node-b"],
        )

        assert pipe.zrange.call_count == 2
        keys_called = [call[0][0] for call in pipe.zrange.call_args_list]
        assert "markers:silo-1:about:node-a" in keys_called
        assert "markers:silo-1:about:node-b" in keys_called


# ---------------------------------------------------------------------------
# get_marker_details
# ---------------------------------------------------------------------------


class TestGetMarkerDetails:
    @pytest.mark.asyncio
    async def test_returns_marker_rows(self, mock_store):
        mock_store.execute_query.return_value = [
            {
                "id": "m-1",
                "marker_type": "Contradiction",
                "status": "pending",
                "detected_at": "2026-05-25T10:00:00+00:00",
                "about_ids": ["node-a"],
            }
        ]

        from context_service.engine.markers import get_marker_details

        result = await get_marker_details(
            store=mock_store,
            silo_id="silo-1",
            marker_ids=["m-1"],
        )

        assert len(result) == 1
        assert result[0]["id"] == "m-1"

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_ids(self, mock_store):
        from context_service.engine.markers import get_marker_details

        result = await get_marker_details(
            store=mock_store,
            silo_id="silo-1",
            marker_ids=[],
        )

        assert result == []
        mock_store.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_silo_and_ids_to_query(self, mock_store):
        mock_store.execute_query.return_value = []

        from context_service.engine.markers import get_marker_details

        await get_marker_details(
            store=mock_store,
            silo_id="silo-99",
            marker_ids=["m-1", "m-2"],
        )

        call_params = mock_store.execute_query.call_args[0][1]
        assert call_params["silo_id"] == "silo-99"
        assert set(call_params["ids"]) == {"m-1", "m-2"}
