"""Tests for reasoning chain applicability matching."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from context_service.engine.chain_applicability import find_applicable_chain

MODULE = "context_service.engine.chain_applicability"


def _make_chain(
    chain_id: str | None = None,
    step_embeddings: list[list[float]] | None = None,
    evidence_used: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": chain_id or str(uuid4()),
        "score": 0.92,
        "step_embeddings": step_embeddings or [],
        "evidence_used": evidence_used or [],
        "payload": {},
    }


def _make_config(
    query_threshold_cold: float = 0.95,
    query_threshold_warm: float = 0.88,
    step_threshold: float = 0.85,
    top_k_candidates: int = 5,
    dtw_latency_warn_ms: float = 50.0,
    dtw_latency_abort_ms: float = 100.0,
) -> MagicMock:
    config = MagicMock()
    config.reasoning_chain_matching.query_threshold_cold = query_threshold_cold
    config.reasoning_chain_matching.query_threshold_warm = query_threshold_warm
    config.reasoning_chain_matching.step_threshold = step_threshold
    config.reasoning_chain_matching.top_k_candidates = top_k_candidates
    config.reasoning_chain_matching.dtw_latency_warn_ms = dtw_latency_warn_ms
    config.reasoning_chain_matching.dtw_latency_abort_ms = dtw_latency_abort_ms
    return config


# ---------------------------------------------------------------------------
# Layer 1: No candidates returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_candidates_returns_none() -> None:
    """Returns None immediately when Qdrant finds no candidates."""
    cfg = _make_config()
    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_session_step_embeddings", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.record_chain_lookup"),
    ):
        result = await find_applicable_chain(
            query="test query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is None


# ---------------------------------------------------------------------------
# Layer 1: Threshold selection (cold vs warm start)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_start_uses_strict_threshold() -> None:
    """Cold start (no step hints) passes the cold threshold to search_chains."""
    cfg = _make_config()
    mock_search = AsyncMock(return_value=[])

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_session_step_embeddings", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", mock_search),
        patch(f"{MODULE}.record_chain_lookup"),
    ):
        await find_applicable_chain(
            query="cold query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    _, kwargs = mock_search.call_args
    assert kwargs["threshold"] == 0.95


@pytest.mark.asyncio
async def test_warm_start_uses_relaxed_threshold() -> None:
    """Warm start (has step hints) passes the warm threshold to search_chains."""
    cfg = _make_config()
    mock_search = AsyncMock(return_value=[])

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(
            f"{MODULE}.get_session_step_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 4],
        ),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", mock_search),
        patch(f"{MODULE}.record_chain_lookup"),
    ):
        await find_applicable_chain(
            query="warm query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    _, kwargs = mock_search.call_args
    assert kwargs["threshold"] == 0.88


# ---------------------------------------------------------------------------
# Layer 2: DTW skipped on cold start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_start_skips_dtw() -> None:
    """Cold start never calls dtw_similarity even when candidates exist."""
    cfg = _make_config()
    chain = _make_chain(step_embeddings=[[0.1] * 4, [0.2] * 4])
    mock_dtw = MagicMock(return_value=0.9)
    mock_ctx_svc = MagicMock()
    mock_ctx_svc._memgraph = AsyncMock()

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_context_service", return_value=mock_ctx_svc),
        patch(f"{MODULE}.get_session_step_embeddings", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[chain]),
        patch(f"{MODULE}.get_accessible_evidence", new_callable=AsyncMock, return_value=set()),
        patch(f"{MODULE}.log_chain_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.record_chain_lookup"),
        patch(f"{MODULE}.dtw_similarity", mock_dtw),
    ):
        result = await find_applicable_chain(
            query="cold query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    mock_dtw.assert_not_called()
    # Chain should still be returned (passed Layer 3 with empty evidence)
    assert result is not None
    assert result["id"] == chain["id"]


# ---------------------------------------------------------------------------
# Layer 2: DTW latency abort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dtw_latency_abort_stops_early() -> None:
    """Aborts candidate loop when cumulative DTW time exceeds abort threshold."""
    cfg = _make_config(
        dtw_latency_warn_ms=5.0,
        dtw_latency_abort_ms=12.0,
    )

    def slow_dtw(*_args: Any) -> float:
        time.sleep(0.008)  # 8 ms per call; two calls exceeds 12 ms abort threshold
        return 0.5  # Below step_threshold; would normally continue

    chains = [_make_chain(step_embeddings=[[0.1] * 4]) for _ in range(5)]

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(
            f"{MODULE}.get_session_step_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 4],
        ),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=chains),
        patch(f"{MODULE}.get_accessible_evidence", new_callable=AsyncMock, return_value=set()),
        patch(f"{MODULE}.record_chain_lookup"),
        patch(f"{MODULE}.dtw_similarity", side_effect=slow_dtw),
    ):
        result = await find_applicable_chain(
            query="warm query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is None


# ---------------------------------------------------------------------------
# Layer 3: Evidence accessibility rejects chains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_inaccessible_skips_chain() -> None:
    """Chains whose evidence is not accessible are skipped."""
    cfg = _make_config()
    required_node = str(uuid4())
    chain = _make_chain(evidence_used=[required_node])

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_session_step_embeddings", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[chain]),
        # Accessible set does NOT include the required node
        patch(
            f"{MODULE}.get_accessible_evidence",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(f"{MODULE}.record_chain_lookup"),
    ):
        result = await find_applicable_chain(
            query="test query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is None


@pytest.mark.asyncio
async def test_accessible_evidence_returns_chain() -> None:
    """Chain is returned when all required evidence is accessible."""
    cfg = _make_config()
    required_node = str(uuid4())
    chain = _make_chain(evidence_used=[required_node])
    mock_ctx_svc = MagicMock()
    mock_ctx_svc._memgraph = AsyncMock()

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_context_service", return_value=mock_ctx_svc),
        patch(f"{MODULE}.get_session_step_embeddings", new_callable=AsyncMock, return_value=[]),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[chain]),
        # Accessible set includes the required node
        patch(
            f"{MODULE}.get_accessible_evidence",
            new_callable=AsyncMock,
            return_value={required_node},
        ),
        patch(f"{MODULE}.log_chain_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.record_chain_lookup"),
    ):
        result = await find_applicable_chain(
            query="test query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is not None
    assert result["id"] == chain["id"]


# ---------------------------------------------------------------------------
# Warm start: chain with passing DTW score is returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warm_start_passing_dtw_returns_chain() -> None:
    """Warm start chain passes DTW threshold and is returned."""
    cfg = _make_config(step_threshold=0.85)
    chain = _make_chain(step_embeddings=[[0.1] * 4, [0.2] * 4])
    mock_ctx_svc = MagicMock()
    mock_ctx_svc._memgraph = AsyncMock()

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(f"{MODULE}.get_context_service", return_value=mock_ctx_svc),
        patch(
            f"{MODULE}.get_session_step_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 4],
        ),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[chain]),
        patch(f"{MODULE}.get_accessible_evidence", new_callable=AsyncMock, return_value=set()),
        patch(f"{MODULE}.log_chain_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.record_chain_lookup"),
        patch(f"{MODULE}.dtw_similarity", return_value=0.90),
    ):
        result = await find_applicable_chain(
            query="warm query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is not None
    assert result["id"] == chain["id"]


@pytest.mark.asyncio
async def test_warm_start_failing_dtw_skips_chain() -> None:
    """Warm start chain below DTW step_threshold is skipped."""
    cfg = _make_config(step_threshold=0.85)
    chain = _make_chain(step_embeddings=[[0.1] * 4])

    with (
        patch(f"{MODULE}.get_settings", return_value=cfg),
        patch(
            f"{MODULE}.get_session_step_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 4],
        ),
        patch(f"{MODULE}.embed_query", new_callable=AsyncMock, return_value=[0.1] * 4),
        patch(f"{MODULE}.search_chains", new_callable=AsyncMock, return_value=[chain]),
        patch(f"{MODULE}.get_accessible_evidence", new_callable=AsyncMock, return_value=set()),
        patch(f"{MODULE}.record_chain_lookup"),
        patch(f"{MODULE}.dtw_similarity", return_value=0.70),  # Below 0.85 threshold
    ):
        result = await find_applicable_chain(
            query="warm query",
            silo_id=str(uuid4()),
            session_id=str(uuid4()),
        )

    assert result is None
