"""Tests for context_belief_state tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

import context_service.mcp.tools.context_belief_state  # noqa: F401
from context_service.mcp.tools.context_belief_state import _context_belief_state
from tests.fakes.fake_graph_store import FakeGraphStore

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_SESSION_ID = str(uuid.uuid4())
_BELIEF_A = str(uuid.uuid4())
_BELIEF_B = str(uuid.uuid4())
_NODE_ID = str(uuid.uuid4())


def _make_belief_row(
    belief_id: str,
    content: str = "the market is bullish",
    confidence: float = 0.8,
    about_ids: list[str] | None = None,
) -> dict:
    return {
        "belief_id": belief_id,
        "content": content,
        "confidence": confidence,
        "created_at": "2026-05-07T00:00:00+00:00",
        "updated_at": "2026-05-07T00:00:00+00:00",
        "about_ids": about_ids or [],
    }


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


class TestContextBeliefStateReturnsBeliefs:
    async def test_returns_beliefs_for_session(self, fake_store):
        fake_store.seed_query_result([_make_belief_row(_BELIEF_A), _make_belief_row(_BELIEF_B)])
        fake_store.seed_query_result([])  # no contradictions

        result = await _context_belief_state(
            session_id=_SESSION_ID, silo_id=_SILO_ID
        )

        assert len(result["working_beliefs"]) == 2
        assert result["session_id"] == _SESSION_ID
        assert result["reflection_suggested"] is False
        assert result["potential_contradictions"] == []

    async def test_empty_session_returns_empty(self, fake_store):
        fake_store.seed_query_result([])
        fake_store.seed_query_result([])

        result = await _context_belief_state(
            session_id=_SESSION_ID, silo_id=_SILO_ID
        )

        assert result["working_beliefs"] == []
        assert result["reflection_suggested"] is False

    async def test_belief_fields_present(self, fake_store):
        fake_store.seed_query_result([_make_belief_row(_BELIEF_A, about_ids=[_NODE_ID])])
        fake_store.seed_query_result([])

        result = await _context_belief_state(session_id=_SESSION_ID, silo_id=_SILO_ID)

        belief = result["working_beliefs"][0]
        assert belief["belief_id"] == _BELIEF_A
        assert belief["content"] == "the market is bullish"
        assert belief["confidence"] == 0.8
        assert belief["about_ids"] == [_NODE_ID]


class TestContextBeliefStateAboutFilter:
    async def test_filters_to_matching_about_ids(self, fake_store):
        other_node = str(uuid.uuid4())
        fake_store.seed_query_result([
            _make_belief_row(_BELIEF_A, about_ids=[_NODE_ID]),
            _make_belief_row(_BELIEF_B, about_ids=[other_node]),
        ])
        fake_store.seed_query_result([])

        result = await _context_belief_state(
            session_id=_SESSION_ID, silo_id=_SILO_ID, about=[_NODE_ID]
        )

        assert len(result["working_beliefs"]) == 1
        assert result["working_beliefs"][0]["belief_id"] == _BELIEF_A

    async def test_no_match_returns_empty_beliefs(self, fake_store):
        fake_store.seed_query_result([_make_belief_row(_BELIEF_A, about_ids=["unrelated"])])
        fake_store.seed_query_result([])

        result = await _context_belief_state(
            session_id=_SESSION_ID, silo_id=_SILO_ID, about=[_NODE_ID]
        )

        assert result["working_beliefs"] == []

    async def test_about_none_returns_all(self, fake_store):
        fake_store.seed_query_result([
            _make_belief_row(_BELIEF_A, about_ids=[_NODE_ID]),
            _make_belief_row(_BELIEF_B, about_ids=[]),
        ])
        fake_store.seed_query_result([])

        result = await _context_belief_state(
            session_id=_SESSION_ID, silo_id=_SILO_ID, about=None
        )

        assert len(result["working_beliefs"]) == 2


class TestContextBeliefStateContradictions:
    async def test_detects_contradictions(self, fake_store):
        fake_store.seed_query_result([_make_belief_row(_BELIEF_A), _make_belief_row(_BELIEF_B)])
        fake_store.seed_query_result([{"belief_a": _BELIEF_A, "belief_b": _BELIEF_B}])

        result = await _context_belief_state(session_id=_SESSION_ID, silo_id=_SILO_ID)

        assert result["reflection_suggested"] is True
        assert len(result["potential_contradictions"]) == 1
        c = result["potential_contradictions"][0]
        assert c["belief_a"] == _BELIEF_A
        assert c["belief_b"] == _BELIEF_B

    async def test_multiple_contradictions(self, fake_store):
        c_id = str(uuid.uuid4())
        fake_store.seed_query_result([
            _make_belief_row(_BELIEF_A),
            _make_belief_row(_BELIEF_B),
            _make_belief_row(c_id),
        ])
        fake_store.seed_query_result([
            {"belief_a": _BELIEF_A, "belief_b": _BELIEF_B},
            {"belief_a": _BELIEF_A, "belief_b": c_id},
        ])

        result = await _context_belief_state(session_id=_SESSION_ID, silo_id=_SILO_ID)

        assert len(result["potential_contradictions"]) == 2
        assert result["reflection_suggested"] is True

    async def test_queries_use_session_and_silo(self, fake_store):
        fake_store.seed_query_result([])
        fake_store.seed_query_result([])

        await _context_belief_state(session_id=_SESSION_ID, silo_id=_SILO_ID)

        assert len(fake_store.query_log) == 2
        for _cypher, params in fake_store.query_log:
            assert params["session_id"] == _SESSION_ID
            assert params["silo_id"] == _SILO_ID
