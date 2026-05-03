"""Unit tests for v1.3b LLM-based pattern detection.

No live LLM or DB required — all tests use FakeGraphStore and a stub LLMProvider.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine.llm_patterns import (
    ALLOWED_PATTERN_TYPES,
    HAIKU_MODEL,
    PatternClassification,
    ProcessResult,
    build_pattern_prompt,
    classify_cluster,
    process_llm_candidates,
)
from context_service.extraction.filter.circuit_breaker import CircuitBreaker
from context_service.llm.base import Usage
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cb(
    failure_threshold: int = 5,
    window_s: float = 60.0,
    cooldown_s: float = 3600.0,
) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=failure_threshold,
        window_s=window_s,
        cooldown_s=cooldown_s,
    )


def _make_llm(
    pattern_type: str = "co_occurrence",
    description: str = "test pattern",
    confidence: float = 0.8,
) -> MagicMock:
    """Return a fake LLMProvider that responds with the given classification."""
    llm = MagicMock()
    llm.extract_structured = AsyncMock(
        return_value=(
            {
                "pattern_type": pattern_type,
                "description": description,
                "confidence": confidence,
                "observed_content_snippets": ["snippet a", "snippet b"],
            },
            Usage(model=HAIKU_MODEL, input_tokens=100, output_tokens=30),
        )
    )
    llm.close = AsyncMock()
    return llm


def _make_clusters(n: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": f"cluster-{i}",
            "facts": [{"content": f"Fact {j} in cluster {i}", "confidence": 0.9} for j in range(3)],
            "fact_ids": [f"fact-{i}-{j}" for j in range(3)],
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# build_pattern_prompt
# ---------------------------------------------------------------------------


def test_build_pattern_prompt_returns_two_messages() -> None:
    facts = [{"content": f"Fact {i}"} for i in range(5)]
    messages = build_pattern_prompt(facts)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Fact 0" in messages[1]["content"]


def test_build_pattern_prompt_truncates_at_50() -> None:
    facts = [{"content": f"Fact {i}"} for i in range(60)]
    messages = build_pattern_prompt(facts)

    user_content = messages[1]["content"]
    # Should mention truncation.
    assert "truncated" in user_content
    # Should only show first 50.
    assert "Fact 49" in user_content
    assert "Fact 50" not in user_content


def test_build_pattern_prompt_uses_text_key_as_fallback() -> None:
    facts = [{"text": "Alternative key content"}]
    messages = build_pattern_prompt(facts)
    assert "Alternative key content" in messages[1]["content"]


def test_build_pattern_prompt_truncates_long_content() -> None:
    facts = [{"content": "x" * 300}]
    messages = build_pattern_prompt(facts)
    # Each fact content is capped at 200 chars.
    assert "x" * 201 not in messages[1]["content"]


# ---------------------------------------------------------------------------
# classify_cluster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_cluster_returns_classification() -> None:
    llm = _make_llm(pattern_type="causal_chain", confidence=0.75)
    result = await classify_cluster(llm, "cluster-1", [{"content": "A caused B"}])

    assert result is not None
    assert result.cluster_id == "cluster-1"
    assert result.pattern_type == "causal_chain"
    assert result.confidence == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_classify_cluster_returns_none_on_timeout() -> None:
    async def _slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(10)
        return ({}, Usage(model=HAIKU_MODEL))

    llm = MagicMock()
    llm.extract_structured = _slow

    result = await classify_cluster(llm, "cluster-timeout", [{"content": "fact"}], timeout_s=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_classify_cluster_returns_none_on_error() -> None:
    llm = MagicMock()
    llm.extract_structured = AsyncMock(side_effect=RuntimeError("API down"))

    result = await classify_cluster(llm, "cluster-err", [{"content": "fact"}])
    assert result is None


@pytest.mark.asyncio
async def test_classify_cluster_returns_none_for_unknown_pattern_type() -> None:
    llm = _make_llm(pattern_type="TOTALLY_MADE_UP", confidence=0.9)
    result = await classify_cluster(llm, "cluster-bad", [{"content": "fact"}])
    assert result is None


@pytest.mark.asyncio
async def test_classify_cluster_truncates_description() -> None:
    llm = _make_llm(pattern_type="co_occurrence", description="d" * 200, confidence=0.9)
    result = await classify_cluster(llm, "cluster-1", [{"content": "fact"}])
    assert result is not None
    assert len(result.description) <= 120


# ---------------------------------------------------------------------------
# PatternClassification — dataclass properties
# ---------------------------------------------------------------------------


def test_pattern_classification_defaults() -> None:
    pc = PatternClassification(
        cluster_id="c1",
        pattern_type="semantic_cluster",
        description="test",
        confidence=0.5,
    )
    assert pc.observed_snippets == []


# ---------------------------------------------------------------------------
# process_llm_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_llm_candidates_accepts_patterns() -> None:
    store = FakeGraphStore()
    # Seed: GET_PATTERN_BY_TYPE_AND_SUBJECT returns empty (new pattern)
    # then CREATE_PATTERN returns edge count
    for _ in range(3):
        store.seed_query_result([])  # GET_PATTERN check
        store.seed_write_result([{"edges_created": 3}])  # CREATE_PATTERN

    llm = _make_llm(pattern_type="co_occurrence", confidence=0.8)
    cb = _make_cb()
    clusters = _make_clusters(3)

    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)

    assert result.patterns_accepted == 3
    assert result.patterns_discarded_low_confidence == 0
    assert result.clusters_errored == 0
    assert not result.circuit_breaker_tripped


@pytest.mark.asyncio
async def test_process_llm_candidates_discards_low_confidence() -> None:
    store = FakeGraphStore()
    llm = _make_llm(pattern_type="co_occurrence", confidence=0.1)
    cb = _make_cb()
    clusters = _make_clusters(2)

    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb, min_confidence=0.3)

    assert result.patterns_accepted == 0
    assert result.patterns_discarded_low_confidence == 2


@pytest.mark.asyncio
async def test_process_llm_candidates_skips_batch_when_cb_open() -> None:
    store = FakeGraphStore()
    llm = _make_llm()
    cb = _make_cb(failure_threshold=1)
    await cb.record_failure()  # trips the breaker immediately

    clusters = _make_clusters(3)
    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)

    assert result.circuit_breaker_tripped
    assert result.patterns_accepted == 0
    # LLM was never called.
    llm.extract_structured.assert_not_called()


@pytest.mark.asyncio
async def test_process_llm_candidates_records_cb_failure_on_error() -> None:
    store = FakeGraphStore()
    llm = MagicMock()
    llm.extract_structured = AsyncMock(side_effect=RuntimeError("boom"))
    cb = _make_cb(failure_threshold=10)

    clusters = _make_clusters(1)
    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)

    assert result.clusters_errored == 1
    # CB should have one failure recorded.
    assert not await cb.is_open()  # threshold not yet reached


@pytest.mark.asyncio
async def test_process_llm_candidates_trips_cb_on_repeated_errors() -> None:
    store = FakeGraphStore()
    llm = MagicMock()
    llm.extract_structured = AsyncMock(side_effect=RuntimeError("boom"))
    cb = _make_cb(failure_threshold=3)

    clusters = _make_clusters(5)
    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)

    # After 3 errors, CB trips and remainder is abandoned.
    assert result.circuit_breaker_tripped or result.clusters_errored >= 3


@pytest.mark.asyncio
async def test_process_llm_candidates_maps_llm_type_to_infra_type() -> None:
    """LLM-only types (e.g. semantic_cluster) are mapped to co_occurrence."""
    store = FakeGraphStore()
    # Seed for new pattern creation.
    store.seed_query_result([])
    store.seed_write_result([{"edges_created": 2}])

    llm = _make_llm(pattern_type="semantic_cluster", confidence=0.7)
    cb = _make_cb()
    clusters = _make_clusters(1)

    result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)

    assert result.patterns_accepted == 1
    # The description stored should include the original llm type.
    write_cypher, write_params = store.write_log[0]
    assert "semantic_cluster" in write_params.get("description", "")


@pytest.mark.asyncio
async def test_process_llm_candidates_handles_persist_error_gracefully() -> None:
    store = FakeGraphStore()
    # Let the pattern check succeed but create fail.
    store.seed_query_result([])  # GET_PATTERN returns empty
    # execute_write will raise because write_log is not pre-seeded — FakeGraphStore
    # returns [] by default; that is fine. Simulate error via patching.

    llm = _make_llm(confidence=0.9)
    cb = _make_cb()
    clusters = _make_clusters(1)

    # Patch create_or_update_pattern to raise.
    async def _patched_create(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("db error")

    import context_service.engine.patterns as pat_mod

    original_cup = pat_mod.create_or_update_pattern
    pat_mod.create_or_update_pattern = _patched_create  # type: ignore[assignment]
    try:
        result = await process_llm_candidates(store, "silo-1", clusters, llm, cb=cb)
    finally:
        pat_mod.create_or_update_pattern = original_cup  # type: ignore[assignment]

    assert result.clusters_errored == 1
    assert result.patterns_accepted == 0


# ---------------------------------------------------------------------------
# ALLOWED_PATTERN_TYPES coverage
# ---------------------------------------------------------------------------


def test_allowed_pattern_types_includes_llm_types() -> None:
    for pt in ("contradictory_claims", "entity_lifecycle", "semantic_cluster"):
        assert pt in ALLOWED_PATTERN_TYPES


def test_allowed_pattern_types_includes_infra_types() -> None:
    for pt in ("temporal_correlation", "co_occurrence", "causal_chain"):
        assert pt in ALLOWED_PATTERN_TYPES


# ---------------------------------------------------------------------------
# ProcessResult defaults
# ---------------------------------------------------------------------------


def test_process_result_defaults() -> None:
    pr = ProcessResult()
    assert pr.patterns_accepted == 0
    assert pr.circuit_breaker_tripped is False
