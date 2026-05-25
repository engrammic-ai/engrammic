"""Tests for recall engagement detection integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides: dict[str, int] = {}


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


@pytest.fixture
def _patch_recall_base(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Base patches for recall tests."""
    captured: dict[str, object] = {}

    async def _fake_context_recall(
        *,
        silo_id: str,
        query: str | None,
        node_ids: list[str] | None,
        depth: int,
        layers: list[str] | None,
        top_k: int,
        bypass_cache: bool = False,
        max_age_seconds: int | None = None,
    ) -> dict[str, object]:
        captured["silo_id"] = silo_id
        return {
            "results": [
                {"node_id": "node-1", "content": "test 1"},
                {"node_id": "node-2", "content": "test 2"},
            ]
        }

    async def _auth() -> object:
        class A:
            org_id = "org-1"
            session_id = "session-1"
            db_user_id = None

        return A()

    monkeypatch.setattr(recall_mod, "_context_recall", _fake_context_recall)
    monkeypatch.setattr(recall_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(recall_mod, "derive_silo_id", lambda _: "silo-1")
    monkeypatch.setattr(recall_mod, "get_preset_resolver", lambda: _FakeResolver())
    # Stub track_tool_usage to avoid auth issues
    monkeypatch.setattr(recall_mod, "track_tool_usage", AsyncMock())
    return captured


@pytest.mark.asyncio
async def test_recall_no_engagement_returns_null(
    _patch_recall_base: dict[str, object],
) -> None:
    """When no markers exist, engagement should be null."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=None),
        ) as mock_engagement,
    ):
        result = await recall_mod._recall_impl(query="test")

    assert "engagement" in result
    assert result["engagement"] is None
    mock_engagement.assert_called_once()


@pytest.mark.asyncio
async def test_recall_with_soft_engagement_returns_engagement_field(
    _patch_recall_base: dict[str, object],
) -> None:
    """When markers exist, engagement field should contain the engagement data."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    engagement_data = {
        "mode": "soft",
        "markers": [
            {
                "marker_id": "marker-1",
                "marker_type": "Contradiction",
                "summary": "Contradiction between node-1 and node-2",
                "node_ids": ["node-1", "node-2"],
                "detected_at": "2026-05-25T00:00:00Z",
                "decision_required": "dismiss",
            }
        ],
    }

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=engagement_data),
        ),
    ):
        result = await recall_mod._recall_impl(query="test")

    assert "engagement" in result
    assert result["engagement"] == engagement_data
    assert result["engagement"]["mode"] == "soft"
    assert len(result["engagement"]["markers"]) == 1


@pytest.mark.asyncio
async def test_recall_engagement_failure_doesnt_break_recall(
    _patch_recall_base: dict[str, object],
) -> None:
    """If engagement detection fails, recall should still succeed with null engagement."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(side_effect=Exception("Redis connection failed")),
        ),
    ):
        result = await recall_mod._recall_impl(query="test")

    # Recall should succeed
    assert "results" in result
    assert len(result["results"]) == 2
    # Engagement should be null due to failure
    assert result["engagement"] is None


@pytest.mark.asyncio
async def test_recall_empty_results_has_null_engagement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When recall returns no results, engagement should be null (no about_ids)."""

    async def _fake_context_recall(**kwargs: object) -> dict[str, object]:
        return {"results": []}

    async def _auth() -> object:
        class A:
            org_id = "org-1"
            session_id = None
            db_user_id = None

        return A()

    monkeypatch.setattr(recall_mod, "_context_recall", _fake_context_recall)
    monkeypatch.setattr(recall_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(recall_mod, "derive_silo_id", lambda _: "silo-1")
    monkeypatch.setattr(recall_mod, "get_preset_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(recall_mod, "track_tool_usage", AsyncMock())

    result = await recall_mod._recall_impl(query="test")

    assert "engagement" in result
    assert result["engagement"] is None


@pytest.mark.asyncio
async def test_recall_hard_mode_returns_empty_results(
    _patch_recall_base: dict[str, object],
) -> None:
    """Hard mode engagement suppresses all recall results."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    engagement_data = {
        "mode": "hard",
        "message": "Resolution required before recall results are available.",
        "markers": [
            {
                "marker_id": "marker-1",
                "marker_type": "Contradiction",
                "summary": "Contradiction between node-1 and node-2",
                "node_ids": ["node-1", "node-2"],
                "detected_at": "2026-05-25T00:00:00Z",
                "decision_required": "dismiss",
            }
        ],
    }

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=engagement_data),
        ),
    ):
        result = await recall_mod._recall_impl(query="test")

    # Results must be empty in hard mode
    assert result["results"] == []
    # Engagement payload is preserved (agent needs to know what to resolve)
    assert result["engagement"]["mode"] == "hard"
    assert len(result["engagement"]["markers"]) == 1
    assert "message" in result["engagement"]


@pytest.mark.asyncio
async def test_recall_soft_mode_returns_normal_results(
    _patch_recall_base: dict[str, object],
) -> None:
    """Soft mode engagement does not suppress recall results."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    engagement_data = {
        "mode": "soft",
        "markers": [
            {
                "marker_id": "marker-1",
                "marker_type": "StaleCommitment",
                "summary": "Commitment commit-1 may be stale",
                "node_ids": ["node-1"],
                "detected_at": "2026-05-25T00:00:00Z",
                "decision_required": "dismiss",
            }
        ],
    }

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=engagement_data),
        ),
    ):
        result = await recall_mod._recall_impl(query="test")

    # Results are present in soft mode
    assert len(result["results"]) == 2
    assert result["engagement"]["mode"] == "soft"


@pytest.mark.asyncio
async def test_recall_hard_mode_also_empties_hypotheses(
    _patch_recall_base: dict[str, object],
) -> None:
    """Hard mode suppresses hypotheses in addition to main results."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    engagement_data = {
        "mode": "hard",
        "message": "Resolution required.",
        "markers": [
            {
                "marker_id": "marker-1",
                "marker_type": "Contradiction",
                "summary": "Contradiction between node-1 and node-2",
                "node_ids": ["node-1", "node-2"],
                "detected_at": "2026-05-25T00:00:00Z",
                "decision_required": "dismiss",
            }
        ],
    }

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=engagement_data),
        ),
    ):
        result = await recall_mod._recall_impl(query="test", include_hypotheses=True)

    assert result["results"] == []
    assert result["hypotheses"] == []
    assert result["engagement"]["mode"] == "hard"


@pytest.mark.asyncio
async def test_recall_passes_session_id_to_engagement(
    _patch_recall_base: dict[str, object],
) -> None:
    """session_id from auth context is forwarded to get_engagement_for_about_set."""
    mock_ctx = MagicMock()
    mock_ctx._redis = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    mock_engagement = AsyncMock(return_value=None)

    with (
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.mcp.tools.recall.get_redis",
            return_value=mock_redis_client,
        ),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=mock_engagement,
        ),
    ):
        await recall_mod._recall_impl(query="test")

    mock_engagement.assert_called_once()
    call_kwargs = mock_engagement.call_args.kwargs
    assert call_kwargs.get("session_id") == "session-1"
