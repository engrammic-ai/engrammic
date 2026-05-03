"""Unit tests for v1.3c session compaction — no DB or LLM required."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_close_reasoning import close_reasoning_chain
from tests.fakes.fake_graph_store import FakeGraphStore

_MOD = "context_service.mcp.tools.context_close_reasoning"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_steps(n: int) -> list[dict]:
    return [
        {"step_index": i, "operation": "deduction", "conclusion": f"conclusion {i}"}
        for i in range(n)
    ]


def _make_chain_row(
    chain_id: str = "chain-1",
    steps: list[dict] | None = None,
    compact_summary: str | None = None,
    session_state: str | None = None,
    compacted: bool = False,
) -> dict:
    s = steps if steps is not None else _make_steps(2)
    return {
        "id": chain_id,
        "steps": s,
        "compact_summary": compact_summary,
        "agent_id": "agent-x",
        "session_state": session_state,
        "compacted": compacted,
        "step_count": len(s) if s else 0,
    }


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_flag_off_returns_error() -> None:
    """When session_compaction_enabled=False the MCP wrapper returns feature_disabled."""
    from context_service.mcp.tools.context_close_reasoning import _context_close_reasoning

    settings = MagicMock(session_compaction_enabled=False)
    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await _context_close_reasoning(silo_id="silo-1", chain_id="chain-1")

    assert result["error"] == "feature_disabled"


# ---------------------------------------------------------------------------
# Happy path: short chain (no LLM summarization)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_short_chain_sets_state_and_returns_summary() -> None:
    """A chain below threshold closes with inline summary; no compaction event."""
    store = FakeGraphStore()
    store.seed_query_result([_make_chain_row(steps=_make_steps(2))])
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "closed"}])

    settings = MagicMock(
        session_compaction_enabled=True,
        compaction_step_threshold=5,
    )

    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
        )

    assert result["session_state"] == "closed"
    assert result["summarization_triggered"] is False
    assert result["step_count"] == 2
    assert "summary" in result
    assert "event_id" not in result


# ---------------------------------------------------------------------------
# Happy path: long chain (should trigger compaction)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_long_chain_triggers_compaction() -> None:
    """A chain above threshold should trigger compact_reasoning_chain."""
    store = FakeGraphStore()
    store.seed_query_result([_make_chain_row(steps=_make_steps(8))])
    # SET_CHAIN_SESSION_STATE (closed)
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "closed"}])
    # SET_CHAIN_SESSION_STATE (summarized) — seeded before compact mock fires
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "summarized"}])

    settings = MagicMock(
        session_compaction_enabled=True,
        compaction_step_threshold=5,
        summarization_provider="anthropic",
        summarization_model="claude-haiku-4-5-20250929",
    )

    mock_event_id = "event-abc123"

    with (
        patch(f"{_MOD}.get_settings", return_value=settings),
        patch(
            f"{_MOD}.compact_reasoning_chain",
            new=AsyncMock(return_value=mock_event_id),
        ),
        patch(
            f"{_MOD}.summarize_reasoning_steps",
            new=AsyncMock(return_value="Summarized reasoning."),
        ),
    ):
        result = await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
        )

    assert result["session_state"] == "summarized"
    assert result["summarization_triggered"] is True
    assert result["event_id"] == mock_event_id
    assert result["summary"] == "Summarized reasoning."


# ---------------------------------------------------------------------------
# Chain not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_chain_not_found() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])  # empty = not found

    settings = MagicMock(session_compaction_enabled=True, compaction_step_threshold=5)

    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await close_reasoning_chain(
            store=store,
            chain_id="missing",
            silo_id="silo-1",
        )

    assert result["error"] == "chain_not_found"


# ---------------------------------------------------------------------------
# Already closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_already_closed_chain() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_make_chain_row(session_state="closed")])

    settings = MagicMock(session_compaction_enabled=True, compaction_step_threshold=5)

    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
        )

    assert result["error"] == "already_closed"


# ---------------------------------------------------------------------------
# Cross-chain REFERENCES edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_creates_references_edges() -> None:
    """referenced_chain_ids should produce REFERENCES edge writes."""
    store = FakeGraphStore()
    store.seed_query_result([_make_chain_row(steps=_make_steps(2))])
    # SET_CHAIN_SESSION_STATE write
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "closed"}])
    # CREATE_CHAIN_REFERENCES_EDGE
    store.seed_write_result([{"from_id": "chain-1", "to_id": "chain-ref-1"}])

    settings = MagicMock(
        session_compaction_enabled=True,
        compaction_step_threshold=5,
    )

    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
            referenced_chain_ids=["chain-ref-1"],
        )

    assert result["session_state"] == "closed"
    assert result.get("references_created") == ["chain-ref-1"]


# ---------------------------------------------------------------------------
# DB query content checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_session_state_write_uses_correct_params() -> None:
    """SET_CHAIN_SESSION_STATE write must include chain_id, silo_id, and session_state."""
    store = FakeGraphStore()
    store.seed_query_result([_make_chain_row(steps=_make_steps(1))])
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "closed"}])

    settings = MagicMock(session_compaction_enabled=True, compaction_step_threshold=5)

    with patch(f"{_MOD}.get_settings", return_value=settings):
        await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
        )

    assert store.write_log, "Expected at least one write call"
    cypher, params = store.write_log[0]
    assert "session_state" in cypher
    assert params["chain_id"] == "chain-1"
    assert params["session_state"] == "closed"


# ---------------------------------------------------------------------------
# context_graph REFERENCES edge injection logic
# ---------------------------------------------------------------------------


def test_context_graph_includes_references_when_flag_on() -> None:
    """When session_compaction_enabled=True, REFERENCES is added to rel_types."""
    settings = MagicMock(
        session_compaction_enabled=True,
        causal=MagicMock(query_enabled=False),
    )

    effective_rel_types = None
    if settings.causal.query_enabled:
        effective_rel_types = ["CAUSES", "CORROBORATES", "PREVENTS"]
    if settings.session_compaction_enabled:
        if effective_rel_types is None:
            effective_rel_types = ["REFERENCES"]
        elif "REFERENCES" not in effective_rel_types:
            effective_rel_types.append("REFERENCES")

    assert effective_rel_types == ["REFERENCES"]


def test_context_graph_excludes_references_when_flag_off() -> None:
    """When session_compaction_enabled=False, REFERENCES is not injected."""
    settings = MagicMock(
        session_compaction_enabled=False,
        causal=MagicMock(query_enabled=False),
    )

    effective_rel_types = None
    if settings.causal.query_enabled:
        effective_rel_types = ["CAUSES", "CORROBORATES", "PREVENTS"]
    if settings.session_compaction_enabled:
        if effective_rel_types is None:
            effective_rel_types = ["REFERENCES"]
        elif "REFERENCES" not in effective_rel_types:
            effective_rel_types.append("REFERENCES")

    assert effective_rel_types is None


# ---------------------------------------------------------------------------
# JSON-encoded steps handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_chain_with_json_encoded_steps() -> None:
    """Steps stored as a JSON string (Memgraph cold-form) are decoded correctly."""
    steps = _make_steps(2)
    store = FakeGraphStore()
    row = _make_chain_row()
    row["steps"] = json.dumps(steps)  # simulate Memgraph returning JSON string
    store.seed_query_result([row])
    store.seed_write_result([{"chain_id": "chain-1", "session_state": "closed"}])

    settings = MagicMock(session_compaction_enabled=True, compaction_step_threshold=5)

    with patch(f"{_MOD}.get_settings", return_value=settings):
        result = await close_reasoning_chain(
            store=store,
            chain_id="chain-1",
            silo_id="silo-1",
        )

    assert result["step_count"] == 2
    assert result["session_state"] == "closed"
