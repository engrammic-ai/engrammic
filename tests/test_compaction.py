"""Unit tests for engine/compaction.py — no DB required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.engine.compaction import (
    _make_event_id,
    batch_compact_chains,
    compact_reasoning_chain,
)
from context_service.engine.summarization import inline_summary
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# inline_summary unit tests (fallback path, no LLM required)
# ---------------------------------------------------------------------------


def _make_steps(n: int) -> list[dict]:
    return [
        {"step_index": i, "operation": "deduction", "conclusion": f"conclusion {i}"}
        for i in range(n)
    ]


def test_inline_summary_empty() -> None:
    assert inline_summary([]) == "(no steps)"


def test_inline_summary_small() -> None:
    steps = _make_steps(3)
    result = inline_summary(steps)
    for i in range(3):
        assert f"conclusion {i}" in result


def test_inline_summary_at_threshold() -> None:
    steps = _make_steps(5)
    result = inline_summary(steps)
    assert "elided" not in result
    for i in range(5):
        assert f"conclusion {i}" in result


def test_inline_summary_large_chain() -> None:
    # inline_summary is the fallback: it always inlines all steps, never elides
    steps = _make_steps(8)
    result = inline_summary(steps)
    for i in range(8):
        assert f"conclusion {i}" in result


def test_inline_summary_unsorted_input() -> None:
    steps = [
        {"step_index": 2, "operation": "analogy", "conclusion": "C"},
        {"step_index": 0, "operation": "deduction", "conclusion": "A"},
        {"step_index": 1, "operation": "synthesis", "conclusion": "B"},
    ]
    result = inline_summary(steps)
    # Should appear in step_index order
    a_pos = result.index("A")
    b_pos = result.index("B")
    c_pos = result.index("C")
    assert a_pos < b_pos < c_pos


# ---------------------------------------------------------------------------
# compact_reasoning_chain — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_hot_chain_creates_event() -> None:
    store = FakeGraphStore()
    steps = _make_steps(3)
    store.seed_query_result(
        [
            {
                "id": "chain-1",
                "steps": steps,
                "compact_summary": None,
                "agent_id": "agent-x",
                "tier": "hot",
                "status": "published",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([{"event_id": "ev-1"}])
    store.seed_write_result([{"chain_id": "chain-1"}])

    event_id = await compact_reasoning_chain(store, "chain-1", "silo-1", "committed")

    assert event_id == _make_event_id("chain-1", "silo-1")

    # First write: CREATE_REASONING_TRACE_EVENT (uses MERGE for idempotency)
    first_write_cypher, first_write_params = store.write_log[0]
    assert "MERGE (e:Event" in first_write_cypher
    assert first_write_params["chain_id"] == "chain-1"
    assert first_write_params["silo_id"] == "silo-1"
    assert first_write_params["agent_id"] == "agent-x"
    assert first_write_params["step_count"] == 3
    assert first_write_params["outcome"] == "committed"
    assert "conclusion 0" in first_write_params["content"]

    # Second write: TOMBSTONE_REASONING_CHAIN
    second_write_cypher, second_write_params = store.write_log[1]
    assert "compacted = true" in second_write_cypher or "compacted" in second_write_cypher
    assert second_write_params["chain_id"] == "chain-1"


@pytest.mark.asyncio
async def test_compact_cold_chain_uses_compact_summary() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "id": "chain-2",
                "steps": None,
                "compact_summary": "Pre-computed cold summary",
                "agent_id": "agent-y",
                "tier": "cold",
                "status": "retracted",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([])
    store.seed_write_result([])

    event_id = await compact_reasoning_chain(store, "chain-2", "silo-1", "abandoned")

    _, params = store.write_log[0]
    assert params["content"] == "Pre-computed cold summary"
    assert params["step_count"] == 0
    assert params["outcome"] == "abandoned"
    assert event_id


# ---------------------------------------------------------------------------
# compact_reasoning_chain — error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_chain_not_found_raises() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])  # empty result = not found

    with pytest.raises(ValueError, match="not found"):
        await compact_reasoning_chain(store, "missing-chain", "silo-1", "expired")


@pytest.mark.asyncio
async def test_compact_already_compacted_raises() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "id": "chain-3",
                "steps": _make_steps(2),
                "compact_summary": None,
                "agent_id": "a",
                "tier": "hot",
                "status": "published",
                "compacted": True,
            }
        ]
    )

    with pytest.raises(ValueError, match="already compacted"):
        await compact_reasoning_chain(store, "chain-3", "silo-1", "committed")


@pytest.mark.asyncio
async def test_compact_chain_no_steps_no_summary_raises() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "id": "chain-4",
                "steps": None,
                "compact_summary": None,
                "agent_id": "a",
                "tier": "cold",
                "status": "published",
                "compacted": False,
            }
        ]
    )

    with pytest.raises(ValueError, match="neither steps nor compact_summary"):
        await compact_reasoning_chain(store, "chain-4", "silo-1", "expired")


# ---------------------------------------------------------------------------
# compacted_by_model propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_hot_chain_passes_compacted_by_model_to_tombstone() -> None:
    """TOMBSTONE_REASONING_CHAIN must receive compacted_by_model (may be None on LLM failure)."""
    store = FakeGraphStore()
    steps = _make_steps(2)
    store.seed_query_result(
        [
            {
                "id": "chain-m",
                "steps": steps,
                "compact_summary": None,
                "agent_id": "agent-m",
                "tier": "hot",
                "status": "published",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([{"event_id": "ev-m"}])
    store.seed_write_result([{"chain_id": "chain-m"}])

    await compact_reasoning_chain(store, "chain-m", "silo-1", "committed")

    # Second write is the tombstone
    second_write_cypher, second_write_params = store.write_log[1]
    assert "compacted_by_model" in second_write_cypher
    assert "compacted_by_model" in second_write_params
    # The value is either a model string or None (when LLM is unavailable in test env)
    model_val = second_write_params["compacted_by_model"]
    assert model_val is None or isinstance(model_val, str)


@pytest.mark.asyncio
async def test_compact_hot_chain_passes_model_string_on_llm_success() -> None:
    """When LLM summarization succeeds, compacted_by_model must equal the model ID string."""
    _MOD = "context_service.engine.compaction"

    store = FakeGraphStore()
    steps = _make_steps(2)
    store.seed_query_result(
        [
            {
                "id": "chain-llm",
                "steps": steps,
                "compact_summary": None,
                "agent_id": "agent-llm",
                "tier": "hot",
                "status": "published",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([{"event_id": "ev-llm"}])
    store.seed_write_result([{"chain_id": "chain-llm"}])

    expected_model_id = "test-model-id-123"

    mock_model_spec = MagicMock()
    mock_model_spec.provider = "anthropic"
    mock_model_spec.model = expected_model_id

    mock_settings = MagicMock()
    mock_settings.models.get_model.return_value = mock_model_spec

    mock_llm_client = MagicMock()

    with (
        patch("context_service.config.settings.get_settings", return_value=mock_settings),
        patch("context_service.llm.build_llm_provider", return_value=mock_llm_client),
        patch(
            f"{_MOD}.summarize_reasoning_steps",
            new=AsyncMock(return_value="LLM-generated summary"),
        ),
    ):
        await compact_reasoning_chain(store, "chain-llm", "silo-1", "committed")

    second_write_cypher, second_write_params = store.write_log[1]
    assert "compacted_by_model" in second_write_cypher
    assert second_write_params["compacted_by_model"] == expected_model_id


@pytest.mark.asyncio
async def test_compact_cold_chain_passes_compacted_by_model_none() -> None:
    """Cold-form compaction has no LLM call, so compacted_by_model must be None."""
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "id": "chain-cold-m",
                "steps": None,
                "compact_summary": "Existing summary",
                "agent_id": "agent-z",
                "tier": "cold",
                "status": "abandoned",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([])
    store.seed_write_result([])

    await compact_reasoning_chain(store, "chain-cold-m", "silo-1", "abandoned")

    second_write_cypher, second_write_params = store.write_log[1]
    assert "compacted_by_model" in second_write_cypher
    assert second_write_params["compacted_by_model"] is None


# ---------------------------------------------------------------------------
# batch_compact_chains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_compact_chains_returns_event_ids() -> None:
    store = FakeGraphStore()

    # GET_COMPACTABLE_CHAINS returns two chain ids
    store.seed_query_result([{"id": "c-a"}, {"id": "c-b"}])

    # For chain c-a: fetch + two writes
    store.seed_query_result(
        [
            {
                "id": "c-a",
                "steps": _make_steps(2),
                "compact_summary": None,
                "agent_id": "ag",
                "tier": "hot",
                "status": "published",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([])
    store.seed_write_result([])

    # For chain c-b: fetch + two writes
    store.seed_query_result(
        [
            {
                "id": "c-b",
                "steps": _make_steps(1),
                "compact_summary": None,
                "agent_id": "ag",
                "tier": "hot",
                "status": "retracted",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([])
    store.seed_write_result([])

    event_ids = await batch_compact_chains(store, "silo-1")

    assert len(event_ids) == 2
    assert _make_event_id("c-a", "silo-1") in event_ids
    assert _make_event_id("c-b", "silo-1") in event_ids


@pytest.mark.asyncio
async def test_batch_compact_skips_bad_chains() -> None:
    """Chains that raise ValueError during compaction are skipped, not propagated."""
    store = FakeGraphStore()

    store.seed_query_result([{"id": "c-good"}, {"id": "c-bad"}])

    # c-good: normal
    store.seed_query_result(
        [
            {
                "id": "c-good",
                "steps": _make_steps(1),
                "compact_summary": None,
                "agent_id": "ag",
                "tier": "hot",
                "status": "published",
                "compacted": False,
            }
        ]
    )
    store.seed_write_result([])
    store.seed_write_result([])

    # c-bad: already compacted
    store.seed_query_result(
        [
            {
                "id": "c-bad",
                "steps": _make_steps(1),
                "compact_summary": None,
                "agent_id": "ag",
                "tier": "hot",
                "status": "published",
                "compacted": True,
            }
        ]
    )

    event_ids = await batch_compact_chains(store, "silo-1")

    assert len(event_ids) == 1
    assert _make_event_id("c-good", "silo-1") in event_ids
