"""Tests for context_update_belief tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

import context_service.mcp.tools.context_update_belief  # noqa: F401
from context_service.mcp.tools.context_update_belief import _context_update_belief
from tests.fakes.fake_graph_store import FakeGraphStore

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_BELIEF_ID = str(uuid.uuid4())


@pytest.fixture
def fake_store():
    return FakeGraphStore()


@pytest.fixture(autouse=True)
def patch_graph_store(fake_store):
    svc = AsyncMock()
    svc.graph_store = fake_store
    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=svc,
    ):
        yield


class TestContextUpdateBeliefSuccess:
    async def test_returns_updated_fields(self, fake_store):
        fake_store.seed_write_result([{"belief_id": _BELIEF_ID}])

        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=0.9,
            reason="new evidence observed",
            silo_id=_SILO_ID,
        )

        assert result["belief_id"] == _BELIEF_ID
        assert result["confidence"] == 0.9
        assert result["reason"] == "new evidence observed"
        assert "updated_at" in result

    async def test_content_revision_included(self, fake_store):
        fake_store.seed_write_result([{"belief_id": _BELIEF_ID}])

        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=0.75,
            reason="refined understanding",
            silo_id=_SILO_ID,
            content="the market is now bearish",
        )

        assert result["content"] == "the market is now bearish"
        assert result["confidence"] == 0.75

    async def test_write_logged_with_correct_params(self, fake_store):
        fake_store.seed_write_result([{"belief_id": _BELIEF_ID}])

        await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=0.6,
            reason="testing",
            silo_id=_SILO_ID,
        )

        assert len(fake_store.write_log) == 1
        _cypher, params = fake_store.write_log[0]
        assert params["belief_id"] == _BELIEF_ID
        assert params["silo_id"] == _SILO_ID
        assert params["confidence"] == 0.6

    async def test_confidence_zero_is_valid(self, fake_store):
        fake_store.seed_write_result([{"belief_id": _BELIEF_ID}])

        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=0.0,
            reason="fully retracted",
            silo_id=_SILO_ID,
        )

        assert result["confidence"] == 0.0
        assert "error" not in result

    async def test_confidence_one_is_valid(self, fake_store):
        fake_store.seed_write_result([{"belief_id": _BELIEF_ID}])

        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=1.0,
            reason="fully confirmed",
            silo_id=_SILO_ID,
        )

        assert result["confidence"] == 1.0
        assert "error" not in result


class TestContextUpdateBeliefValidation:
    async def test_rejects_confidence_above_one(self, fake_store):
        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=1.1,
            reason="bad call",
            silo_id=_SILO_ID,
        )

        assert result["error"] == "invalid_confidence"
        assert fake_store.write_log == []

    async def test_rejects_confidence_below_zero(self, fake_store):
        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=-0.1,
            reason="bad call",
            silo_id=_SILO_ID,
        )

        assert result["error"] == "invalid_confidence"
        assert fake_store.write_log == []


class TestContextUpdateBeliefNotFound:
    async def test_not_found_when_store_returns_empty(self, fake_store):
        # write returns nothing -> belief not found in silo
        fake_store.seed_write_result([])

        result = await _context_update_belief(
            belief_id=_BELIEF_ID,
            confidence=0.5,
            reason="test",
            silo_id=_SILO_ID,
        )

        assert result["error"] == "not_found"
        assert _BELIEF_ID in result["message"]
