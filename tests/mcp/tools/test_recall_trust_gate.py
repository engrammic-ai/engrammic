"""Tests for trust gate wiring in recall._recall_impl."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides: dict[str, int] = {}


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


FAKE: dict[str, object] = {
    "results": [
        {"node_id": "ok", "confidence": 0.9, "conflict_status": "none"},
        {"node_id": "contested", "confidence": 0.9, "conflict_status": "unresolved"},
    ],
    "total_candidates": 2,
}


@pytest.fixture
def patched_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all _recall_impl dependencies and override _context_recall with FAKE."""

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
        min_threshold: float | None = None,
    ) -> dict[str, object]:
        import copy

        return copy.deepcopy(FAKE)

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
    monkeypatch.setattr(recall_mod, "track_tool_usage", AsyncMock())


@pytest.mark.asyncio
async def test_recall_withholds_unresolved_conflict(patched_recall: None) -> None:
    """Trust gate withholds items with conflict_status == 'unresolved' by default."""
    mock_ctx = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    with (
        patch("context_service.mcp.server.get_context_service", return_value=mock_ctx),
        patch("context_service.mcp.tools.recall.get_redis", return_value=mock_redis_client),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=None),
        ),
    ):
        out = await recall_mod._recall_impl(query="anything")

    assert [n["node_id"] for n in out["results"]] == ["ok"]
    assert out["withheld"]["count"] == 1
    assert "include_withheld" in out["withheld"]["message"]


@pytest.mark.asyncio
async def test_recall_include_withheld_returns_all(patched_recall: None) -> None:
    """When include_withheld=True, trust gate passes all items through."""
    mock_ctx = MagicMock()
    mock_ctx._memgraph = MagicMock()
    mock_redis_client = MagicMock()
    mock_redis_client._redis = MagicMock()

    with (
        patch("context_service.mcp.server.get_context_service", return_value=mock_ctx),
        patch("context_service.mcp.tools.recall.get_redis", return_value=mock_redis_client),
        patch(
            "context_service.engine.engagement.get_engagement_for_about_set",
            new=AsyncMock(return_value=None),
        ),
    ):
        out = await recall_mod._recall_impl(query="anything", include_withheld=True)

    assert len(out["results"]) == 2
    assert out["withheld"]["count"] == 0
