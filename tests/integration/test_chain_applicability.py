"""Integration tests for reasoning chain applicability matching.

Three-layer funnel under test:
  1. Query intent similarity (Qdrant ANN).
  2. Step-level DTW similarity (warm start only).
  3. Evidence accessibility check.

Architecture note: search_chains() queries the standard per-silo Qdrant
collection (ctx_<silo_id>) via EngineQdrantStore. The context_store tool
writes chain query embeddings to a separate "reasoning_chains" collection,
so there is currently no code path that automatically seeds ctx_<silo_id>
from a ReasoningChain write. These tests therefore seed Qdrant directly to
exercise the full find_applicable_chain funnel.

Requires a live Qdrant instance on localhost:6333.
Skipped automatically when the stack is not running.
"""

from __future__ import annotations

import contextlib
import math
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from context_service.engine.chain_applicability import find_applicable_chain
from context_service.engine.qdrant_store import EngineQdrantStore
from context_service.stores.qdrant import QdrantClient

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def _check_qdrant_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 6333))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


qdrant_available = pytest.mark.skipif(
    not _check_qdrant_available(),
    reason="Qdrant not running on localhost:6333",
)


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------


def _get_vector_dim() -> int:
    try:
        from context_service.config.config_loader import load_config

        return int(load_config("embeddings")["dimensions"])
    except (FileNotFoundError, KeyError):
        return 1024


_VECTOR_DIM = _get_vector_dim()


def _fake_vector(seed: int, dim: int = _VECTOR_DIM) -> list[float]:
    """Return a deterministic unit-length vector seeded by an integer."""
    raw = [math.sin(seed * (i + 1) * 0.1) for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def qdrant_client() -> QdrantClient:
    return QdrantClient(url="http://localhost:6333", vector_size=_VECTOR_DIM)


@pytest.fixture
async def engine_store(qdrant_client: QdrantClient) -> AsyncIterator[EngineQdrantStore]:
    """Yield an EngineQdrantStore and close the underlying client after the test."""
    store = EngineQdrantStore(qdrant_client)
    yield store
    # Client is already closed by find_applicable_chain's own store; close again
    # is a no-op on AsyncQdrantClient, but call to keep teardown explicit.
    with contextlib.suppress(Exception):
        await store.close()


@pytest.fixture
def silo_id_a() -> str:
    return f"test-chain-a-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def silo_id_b() -> str:
    return f"test-chain-b-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


async def _cleanup_silo_collection(silo_id: str) -> None:
    """Delete the per-silo Qdrant collection created during a test."""
    client = QdrantClient(url="http://localhost:6333", vector_size=_VECTOR_DIM)
    store = EngineQdrantStore(client)
    with contextlib.suppress(Exception):
        await store.delete_collection(silo_id)
    with contextlib.suppress(Exception):
        await store.close()


# ---------------------------------------------------------------------------
# Test: end-to-end flow
# ---------------------------------------------------------------------------


@qdrant_available
@pytest.mark.integration
class TestFindApplicableChainEndToEnd:
    """Seed a chain point into Qdrant, then find it via find_applicable_chain."""

    async def test_chain_found_when_query_matches(
        self,
        engine_store: EngineQdrantStore,
        silo_id_a: str,
        session_id: str,
    ) -> None:
        """A chain seeded with vector V should be returned when query embeds to V."""
        chain_id = uuid.uuid4()
        seed = 42
        vec = _fake_vector(seed)

        # Seed the chain's query embedding directly into the per-silo collection.
        await engine_store.upsert(
            node_id=chain_id,
            vector=vec,
            silo_id=silo_id_a,
            node_type="ReasoningChain",
        )

        # Patch embed_query to return the exact same vector, guaranteeing
        # cosine similarity == 1.0, which clears any configured threshold.
        with patch(
            "context_service.engine.chain_applicability.embed_query",
            AsyncMock(return_value=vec),
        ):
            result = await find_applicable_chain(
                query="reasoning query that matches the seeded chain",
                silo_id=silo_id_a,
                session_id=session_id,
            )

        assert result is not None, (
            "find_applicable_chain should return the seeded chain when "
            "query embedding exactly matches the stored vector"
        )
        assert result["id"] == str(chain_id), (
            f"Expected chain id {chain_id}, got {result['id']}"
        )

        # Cleanup
        await _cleanup_silo_collection(silo_id_a)

    async def test_no_chain_found_when_no_candidates_above_threshold(
        self,
        silo_id_a: str,
        session_id: str,
    ) -> None:
        """Empty silo (no seeded chains) should return None without error."""
        vec = _fake_vector(99)

        with patch(
            "context_service.engine.chain_applicability.embed_query",
            AsyncMock(return_value=vec),
        ):
            result = await find_applicable_chain(
                query="query for a chain that does not exist",
                silo_id=silo_id_a,
                session_id=session_id,
            )

        assert result is None

        # Cleanup (collection may not exist; suppress)
        await _cleanup_silo_collection(silo_id_a)

    async def test_chain_skipped_when_evidence_inaccessible(
        self,
        engine_store: EngineQdrantStore,
        silo_id_a: str,
        session_id: str,
    ) -> None:
        """Chains whose evidence_used is not accessible should be skipped (Layer 3)."""
        chain_id = uuid.uuid4()
        seed = 7
        vec = _fake_vector(seed)

        await engine_store.upsert(
            node_id=chain_id,
            vector=vec,
            silo_id=silo_id_a,
            node_type="ReasoningChain",
        )

        # search_chains currently returns evidence_used=[] for all candidates
        # (stub implementation). Manually override search_chains to simulate a
        # chain that requires evidence node "ev-missing" that is not accessible.
        async def _search_with_evidence(
            query_embedding: list[float],
            top_k: int,
            threshold: float,
            silo_id: str,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "id": str(chain_id),
                    "score": 0.99,
                    "step_embeddings": [],
                    "evidence_used": ["ev-node-missing"],
                    "payload": {},
                }
            ]

        # get_accessible_evidence returns empty set (stub), so a chain requiring
        # "ev-node-missing" should fail Layer 3 and be skipped.
        with (
            patch(
                "context_service.engine.chain_applicability.embed_query",
                AsyncMock(return_value=vec),
            ),
            patch(
                "context_service.engine.chain_applicability.search_chains",
                _search_with_evidence,
            ),
        ):
            result = await find_applicable_chain(
                query="query for a chain with inaccessible evidence",
                silo_id=silo_id_a,
                session_id=session_id,
            )

        assert result is None, (
            "Chain with inaccessible evidence should be filtered by Layer 3"
        )

        await _cleanup_silo_collection(silo_id_a)


# ---------------------------------------------------------------------------
# Test: cross-silo isolation
# ---------------------------------------------------------------------------


@qdrant_available
@pytest.mark.integration
class TestCrossSimoIsolation:
    """Chains from one silo must not be returned when searching another silo."""

    async def test_chain_in_silo_a_not_found_from_silo_b(
        self,
        engine_store: EngineQdrantStore,
        silo_id_a: str,
        silo_id_b: str,
        session_id: str,
    ) -> None:
        """A chain seeded in silo A should be invisible to a query against silo B."""
        chain_id = uuid.uuid4()
        seed = 55
        vec = _fake_vector(seed)

        # Seed only in silo A.
        await engine_store.upsert(
            node_id=chain_id,
            vector=vec,
            silo_id=silo_id_a,
            node_type="ReasoningChain",
        )

        # Query against silo B — different Qdrant collection, should be empty.
        with patch(
            "context_service.engine.chain_applicability.embed_query",
            AsyncMock(return_value=vec),
        ):
            result = await find_applicable_chain(
                query="query that would match the chain in silo A",
                silo_id=silo_id_b,
                session_id=session_id,
            )

        assert result is None, (
            "Chain seeded in silo A must not be returned when querying silo B"
        )

        # Cleanup both silos
        await _cleanup_silo_collection(silo_id_a)
        await _cleanup_silo_collection(silo_id_b)

    async def test_same_chain_id_different_silos_isolated(
        self,
        engine_store: EngineQdrantStore,
        silo_id_a: str,
        silo_id_b: str,
        session_id: str,
    ) -> None:
        """The same chain_id seeded in both silos is found only from its own silo."""
        chain_id = uuid.uuid4()
        seed_a = 11
        seed_b = 22
        vec_a = _fake_vector(seed_a)
        vec_b = _fake_vector(seed_b)

        # Seed the same chain_id in both silos with different vectors.
        await engine_store.upsert(
            node_id=chain_id, vector=vec_a, silo_id=silo_id_a, node_type="ReasoningChain"
        )
        await engine_store.upsert(
            node_id=chain_id, vector=vec_b, silo_id=silo_id_b, node_type="ReasoningChain"
        )

        # Query silo A with vec_a — should find the chain.
        with patch(
            "context_service.engine.chain_applicability.embed_query",
            AsyncMock(return_value=vec_a),
        ):
            result_a = await find_applicable_chain(
                query="silo A query",
                silo_id=silo_id_a,
                session_id=session_id,
            )

        assert result_a is not None, "Chain should be found in silo A"
        assert result_a["id"] == str(chain_id)

        # Query silo B with vec_a (mismatch) — vec_a is orthogonal to what was
        # seeded in silo B, so it should not exceed the cold-start threshold.
        with patch(
            "context_service.engine.chain_applicability.embed_query",
            AsyncMock(return_value=vec_a),
        ):
            result_b = await find_applicable_chain(
                query="silo B query with silo A vector",
                silo_id=silo_id_b,
                session_id=session_id,
            )

        # Because vec_a and vec_b are orthogonal fake vectors, the cosine score
        # will be well below the cold-start threshold (0.95) so nothing returns.
        assert result_b is None, (
            "Query with silo A vector should not find anything in silo B "
            "(orthogonal vectors, below cold-start threshold)"
        )

        await _cleanup_silo_collection(silo_id_a)
        await _cleanup_silo_collection(silo_id_b)


# ---------------------------------------------------------------------------
# Test: cold start vs warm start thresholds
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestColdVsWarmStartThresholds:
    """Verify that cold start uses query_threshold_cold and warm start uses query_threshold_warm.

    These tests do not require live infrastructure — they patch search_chains
    and verify the threshold argument passed to it.
    """

    async def test_cold_start_uses_stricter_threshold(self, session_id: str) -> None:
        """With no session step embeddings (cold start), the stricter threshold is used."""
        from context_service.config.settings import get_settings

        settings = get_settings()
        expected_threshold = settings.reasoning_chain_matching.query_threshold_cold

        captured: dict[str, Any] = {}

        async def _capture_search(
            query_embedding: list[float],
            top_k: int,
            threshold: float,
            silo_id: str,
        ) -> list[dict[str, Any]]:
            captured["threshold"] = threshold
            return []  # No candidates; triggers None return.

        silo_id = f"test-threshold-{uuid.uuid4().hex[:8]}"
        vec = _fake_vector(1)

        with (
            patch(
                "context_service.engine.chain_applicability.embed_query",
                AsyncMock(return_value=vec),
            ),
            patch(
                "context_service.engine.chain_applicability.search_chains",
                _capture_search,
            ),
            # get_session_step_embeddings returns [] by default (cold start).
        ):
            await find_applicable_chain(
                query="cold start query",
                silo_id=silo_id,
                session_id=session_id,
            )

        assert "threshold" in captured, "search_chains was not called"
        assert captured["threshold"] == pytest.approx(expected_threshold), (
            f"Cold start should use threshold {expected_threshold}, "
            f"got {captured['threshold']}"
        )

    async def test_warm_start_uses_relaxed_threshold(self, session_id: str) -> None:
        """With session step embeddings present (warm start), the relaxed threshold is used."""
        from context_service.config.settings import get_settings

        settings = get_settings()
        expected_threshold = settings.reasoning_chain_matching.query_threshold_warm

        # Warm start: step hints are a non-empty list.
        warm_step_hints = [_fake_vector(i) for i in range(3)]

        captured: dict[str, Any] = {}

        async def _capture_search(
            query_embedding: list[float],
            top_k: int,
            threshold: float,
            silo_id: str,
        ) -> list[dict[str, Any]]:
            captured["threshold"] = threshold
            return []

        silo_id = f"test-threshold-{uuid.uuid4().hex[:8]}"
        vec = _fake_vector(2)

        with (
            patch(
                "context_service.engine.chain_applicability.embed_query",
                AsyncMock(return_value=vec),
            ),
            patch(
                "context_service.engine.chain_applicability.search_chains",
                _capture_search,
            ),
            patch(
                "context_service.engine.chain_applicability.get_session_step_embeddings",
                AsyncMock(return_value=warm_step_hints),
            ),
        ):
            await find_applicable_chain(
                query="warm start query",
                silo_id=silo_id,
                session_id=session_id,
            )

        assert "threshold" in captured, "search_chains was not called"
        assert captured["threshold"] == pytest.approx(expected_threshold), (
            f"Warm start should use threshold {expected_threshold}, "
            f"got {captured['threshold']}"
        )

    async def test_cold_threshold_stricter_than_warm(self) -> None:
        """Sanity check: cold threshold should be >= warm threshold per config defaults."""
        from context_service.config.settings import get_settings

        settings = get_settings()
        cold = settings.reasoning_chain_matching.query_threshold_cold
        warm = settings.reasoning_chain_matching.query_threshold_warm

        assert cold >= warm, (
            f"Cold start threshold ({cold}) should be >= warm start threshold ({warm}); "
            "cold start lacks step hints so must be more selective"
        )

    async def test_warm_start_skips_dtw_when_candidate_has_no_step_embeddings(
        self, session_id: str
    ) -> None:
        """In warm start, candidates without step_embeddings are skipped (no DTW possible)."""
        chain_id = str(uuid.uuid4())
        warm_step_hints = [_fake_vector(i) for i in range(2)]

        async def _search_empty_steps(
            query_embedding: list[float],
            top_k: int,
            threshold: float,
            silo_id: str,
        ) -> list[dict[str, Any]]:
            # Return a candidate with empty step_embeddings.
            return [
                {
                    "id": chain_id,
                    "score": 0.95,
                    "step_embeddings": [],
                    "evidence_used": [],
                    "payload": {},
                }
            ]

        silo_id = f"test-dtw-skip-{uuid.uuid4().hex[:8]}"
        vec = _fake_vector(3)

        with (
            patch(
                "context_service.engine.chain_applicability.embed_query",
                AsyncMock(return_value=vec),
            ),
            patch(
                "context_service.engine.chain_applicability.search_chains",
                _search_empty_steps,
            ),
            patch(
                "context_service.engine.chain_applicability.get_session_step_embeddings",
                AsyncMock(return_value=warm_step_hints),
            ),
        ):
            result = await find_applicable_chain(
                query="warm start query with no step embeddings in candidate",
                silo_id=silo_id,
                session_id=session_id,
            )

        # Candidate is skipped because it has no step_embeddings for DTW comparison.
        assert result is None, (
            "Warm-start candidates with empty step_embeddings should be skipped"
        )
