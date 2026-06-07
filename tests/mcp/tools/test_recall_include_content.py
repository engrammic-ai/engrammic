"""Tests for include_content param threading in recall._recall_impl."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides: dict[str, int] = {}


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


@pytest.fixture
def _patch_with_capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch _recall_impl dependencies; capture include_content forwarded to _context_recall."""
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
        min_threshold: float | None = None,
        include_content: bool | None = True,
    ) -> dict[str, object]:
        captured["include_content"] = include_content
        # Return nodes with full content so callers can verify the pass-through
        return {
            "results": [
                {
                    "node_id": "node-1",
                    "content": "full content text",
                    "layer": "memory",
                    "tier": "COLD",
                    "confidence": 0.9,
                }
            ]
        }

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
    return captured


@pytest.mark.asyncio
async def test_recall_default_forwards_include_content_true(
    _patch_with_capture: dict[str, object],
) -> None:
    """Calling _recall_impl without include_content forwards True to _context_recall (default)."""
    await recall_mod._recall_impl(query="test query")
    assert _patch_with_capture["include_content"] is True


@pytest.mark.asyncio
async def test_recall_explicit_false_forwards_include_content_false(
    _patch_with_capture: dict[str, object],
) -> None:
    """Calling _recall_impl with include_content=False forwards False to _context_recall."""
    await recall_mod._recall_impl(query="test query", include_content=False)
    assert _patch_with_capture["include_content"] is False


@pytest.mark.asyncio
async def test_recall_explicit_none_forwards_include_content_none(
    _patch_with_capture: dict[str, object],
) -> None:
    """Calling _recall_impl with include_content=None forwards None (tier-based policy)."""
    await recall_mod._recall_impl(query="test query", include_content=None)
    assert _patch_with_capture["include_content"] is None


@pytest.mark.asyncio
async def test_recall_explicit_true_forwards_include_content_true(
    _patch_with_capture: dict[str, object],
) -> None:
    """Explicit include_content=True is also forwarded correctly."""
    await recall_mod._recall_impl(query="test query", include_content=True)
    assert _patch_with_capture["include_content"] is True
