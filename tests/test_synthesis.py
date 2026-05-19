"""Unit tests for engine/synthesis.py — no DB or real LLM required."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.engine.synthesis import (
    _SYNTHESIS_SYSTEM_PROMPT,
    MIN_FACTS_FOR_BELIEF,
    InsufficientEvidenceError,
    _average_confidence,
    _build_synthesis_prompt,
    _make_belief_id,
    check_belief_coverage,
    synthesize_belief,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fact_rows(n: int, confidence: float = 0.9) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": f"fact-{i}",
            "content": f"Fact content number {i}",
            "confidence": confidence,
            "valid_from": "2026-01-01T00:00:00+00:00",
        }
        for i in range(n)
    ]


def _make_llm(response: str = "Synthesised belief statement.") -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=(response, None))
    return llm


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_make_belief_id_deterministic() -> None:
    a = _make_belief_id("cluster-1", "silo-1")
    b = _make_belief_id("cluster-1", "silo-1")
    assert a == b


def test_make_belief_id_differs_by_cluster() -> None:
    a = _make_belief_id("cluster-1", "silo-1")
    b = _make_belief_id("cluster-2", "silo-1")
    assert a != b


def test_make_belief_id_differs_by_silo() -> None:
    a = _make_belief_id("cluster-1", "silo-1")
    b = _make_belief_id("cluster-1", "silo-2")
    assert a != b


def test_average_confidence_empty() -> None:
    assert _average_confidence([]) == 0.0


def test_average_confidence_uniform() -> None:
    facts = _make_fact_rows(4, confidence=0.8)
    assert abs(_average_confidence(facts) - 0.8) < 1e-9


def test_average_confidence_mixed() -> None:
    facts = [
        {"confidence": 0.6},
        {"confidence": 1.0},
    ]
    assert abs(_average_confidence(facts) - 0.8) < 1e-9


def test_build_synthesis_prompt_includes_content() -> None:
    facts = _make_fact_rows(3)
    prompt = _build_synthesis_prompt(facts)
    for f in facts:
        assert f["content"] in prompt


def test_build_synthesis_prompt_numbered() -> None:
    facts = _make_fact_rows(3)
    prompt = _build_synthesis_prompt(facts)
    assert "1." in prompt
    assert "2." in prompt
    assert "3." in prompt


# ---------------------------------------------------------------------------
# synthesize_belief — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_belief_creates_belief_node() -> None:
    store = FakeGraphStore()
    store.seed_query_result(_make_fact_rows(4))
    store.seed_write_result([{"belief_id": "b-1", "edges_created": 4}])

    llm = _make_llm("All four facts point to the same conclusion.")

    belief_id = await synthesize_belief(store, "cluster-1", "silo-1", llm)

    assert belief_id == _make_belief_id("cluster-1", "silo-1")

    # Verify LLM was called with a system message and facts in the user message
    call_args = llm.complete.call_args
    messages = call_args.kwargs["messages"] if call_args.kwargs else call_args[0][0]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _SYNTHESIS_SYSTEM_PROMPT
    assert any("Fact content" in m["content"] for m in messages)


@pytest.mark.asyncio
async def test_synthesize_belief_write_params() -> None:
    store = FakeGraphStore()
    facts = _make_fact_rows(3, confidence=0.75)
    store.seed_query_result(facts)
    store.seed_write_result([{"belief_id": "b-x", "edges_created": 3}])

    llm = _make_llm("Belief text.")

    await synthesize_belief(store, "c-1", "s-1", llm)

    cypher, params = store.write_log[0]
    assert "Belief" in cypher
    assert params["silo_id"] == "s-1"
    assert params["evidence_count"] == 3
    assert abs(params["confidence"] - 0.75) < 1e-9
    assert params["content"] == "Belief text."
    # fact_ids are now passed in the second write (edge creation)
    if len(store.write_log) > 1:
        _, edge_params = store.write_log[1]
        assert sorted(edge_params["fact_ids"]) == sorted(f["fact_id"] for f in facts)


@pytest.mark.asyncio
async def test_synthesize_belief_strips_whitespace_from_llm_output() -> None:
    store = FakeGraphStore()
    store.seed_query_result(_make_fact_rows(3))
    store.seed_write_result([{"belief_id": "b-x", "edges_created": 3}])

    llm = _make_llm("  Trimmed belief.  \n")

    await synthesize_belief(store, "c-1", "s-1", llm)

    _, params = store.write_log[0]
    assert params["content"] == "Trimmed belief."


# ---------------------------------------------------------------------------
# synthesize_belief — density threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_belief_raises_on_too_few_facts() -> None:
    store = FakeGraphStore()
    store.seed_query_result(_make_fact_rows(MIN_FACTS_FOR_BELIEF - 1))

    llm = _make_llm()

    with pytest.raises(InsufficientEvidenceError, match="minimum required"):
        await synthesize_belief(store, "c-sparse", "s-1", llm)


@pytest.mark.asyncio
async def test_synthesize_belief_raises_on_empty_cluster() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])  # no facts

    llm = _make_llm()

    with pytest.raises(InsufficientEvidenceError):
        await synthesize_belief(store, "c-empty", "s-1", llm)


@pytest.mark.asyncio
async def test_synthesize_belief_succeeds_at_exact_threshold() -> None:
    store = FakeGraphStore()
    store.seed_query_result(_make_fact_rows(MIN_FACTS_FOR_BELIEF))
    store.seed_write_result([{"belief_id": "b-exact", "edges_created": MIN_FACTS_FOR_BELIEF}])

    llm = _make_llm("Exactly at threshold.")

    belief_id = await synthesize_belief(store, "c-exact", "s-1", llm)

    assert belief_id  # not empty


# ---------------------------------------------------------------------------
# check_belief_coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_belief_coverage_found() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [{"belief_id": "b-1", "content": "The sky is blue.", "confidence": 0.95}]
    )

    result = await check_belief_coverage(store, "silo-1", "sky")

    assert result is not None
    assert result["belief_id"] == "b-1"

    cypher, params = store.query_log[0]
    assert "Belief" in cypher
    assert params["subject"] == "sky"
    assert params["silo_id"] == "silo-1"


@pytest.mark.asyncio
async def test_check_belief_coverage_not_found() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    result = await check_belief_coverage(store, "silo-1", "quantum gravity")

    assert result is None
