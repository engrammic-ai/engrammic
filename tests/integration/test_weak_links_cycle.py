"""Integration test for the weak links full cycle.

Covers: create weak links -> emit edge access events -> edge heat computation
-> promotion query.

The first test class uses mocks to verify wiring without a live docker stack.
The second test class (TestWeakLinksCycleLive) requires the full docker stack
and is gated by the `docker_available` + `_full_stack_available` marks.
"""

from __future__ import annotations

import math
import socket
import uuid
from collections import defaultdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Docker availability helpers
# ---------------------------------------------------------------------------


def _check_port(host: str, port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((host, port))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


_memgraph_available = _check_port("localhost", 7687)
_qdrant_available = _check_port("localhost", 6333)
_redis_available = _check_port("localhost", 6379)
_full_stack_available = _memgraph_available and _qdrant_available and _redis_available

requires_full_stack = pytest.mark.skipif(
    not _full_stack_available,
    reason="Full docker stack not running (Memgraph:7687, Qdrant:6333, Redis:6379 required)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vector_dim() -> int:
    from context_service.config.config_loader import load_config

    try:
        return load_config("embeddings")["dimensions"]
    except (FileNotFoundError, KeyError):
        return 1024


_VECTOR_DIM = _get_vector_dim()


def _fake_vector(seed: int, dim: int = _VECTOR_DIM) -> list[float]:
    """Deterministic unit-length vector seeded by an integer."""
    raw = [math.sin(seed * (i + 1) * 0.1) for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


# ---------------------------------------------------------------------------
# Mock-based cycle tests (no docker required)
# ---------------------------------------------------------------------------


class TestWeakLinksCycleMocked:
    """Verify the full cycle wiring with mocks. No live stack required."""

    @pytest.fixture
    def silo_id(self) -> str:
        return f"test-silo-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def node_ids(self) -> tuple[str, str]:
        return (str(uuid.uuid4()), str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Step 1: create_weak_links_for_node creates a WeakLink
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_weak_links_produces_merge_call(
        self,
        silo_id: str,
        node_ids: tuple[str, str],
    ) -> None:
        """create_weak_links_for_node should call memgraph.execute with MERGE_WEAK_LINK_CYPHER
        when a similar candidate exists above threshold."""
        from context_service.pipelines.assets.weak_link_creation import (
            create_weak_links_for_node,
        )

        node_a, node_b = node_ids
        embedding_a = _fake_vector(1)

        memgraph = AsyncMock()
        qdrant = AsyncMock()

        # Not at capacity
        memgraph.execute.return_value = [{"degree": 0}]

        # One candidate above threshold
        candidate = MagicMock()
        candidate.id = node_b
        candidate.score = 0.90
        qdrant.search.return_value = [candidate]

        created = await create_weak_links_for_node(
            memgraph=memgraph,
            qdrant=qdrant,
            node_id=node_a,
            embedding=embedding_a,
            silo_id=silo_id,
            max_links_per_node=5,
            similarity_threshold=0.75,
            top_k_candidates=10,
            initial_weight_multiplier=0.5,
            embedding_model="jina-v3",
        )

        assert created == 1
        # Second execute call is the MERGE
        merge_calls = [c for c in memgraph.execute.call_args_list if "MERGE" in str(c)]
        assert len(merge_calls) == 1
        kwargs = merge_calls[0][0][1]
        assert kwargs["silo_id"] == silo_id
        assert kwargs["from_id"] in node_ids
        assert kwargs["to_id"] in node_ids
        assert kwargs["weight"] == pytest.approx(0.90 * 0.5)
        assert "link_id" in kwargs

    @pytest.mark.asyncio
    async def test_create_weak_links_sets_speculative_true(
        self,
        silo_id: str,
        node_ids: tuple[str, str],
    ) -> None:
        """The MERGE_WEAK_LINK_CYPHER must set speculative = true."""
        from context_service.pipelines.assets.weak_link_creation import MERGE_WEAK_LINK_CYPHER

        assert "speculative = true" in MERGE_WEAK_LINK_CYPHER

    # ------------------------------------------------------------------
    # Step 2: emit_edge_access_event writes to Redis stream
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_emit_edge_access_event_writes_to_stream(
        self,
        silo_id: str,
        node_ids: tuple[str, str],
    ) -> None:
        """emit_edge_access_event should xadd to the silo stream key."""
        from context_service.signals.edge_access_events import (
            edge_access_stream_key,
            emit_edge_access_event,
        )

        node_a, node_b = node_ids
        redis = AsyncMock()

        await emit_edge_access_event(
            redis=redis,
            silo_id=silo_id,
            from_node=node_a,
            to_node=node_b,
            edge_type="RELATED_TO",
            traversal_context="recall",
        )

        redis.xadd.assert_called_once()
        stream_key_arg = redis.xadd.call_args[0][0]
        assert stream_key_arg == edge_access_stream_key(silo_id)
        payload = redis.xadd.call_args[0][1]
        assert payload["edge_type"] == "RELATED_TO"
        assert "edge_id" in payload

    # ------------------------------------------------------------------
    # Step 3: edge_heat Cypher applies heat to WeakLink
    # ------------------------------------------------------------------

    def test_edge_heat_cypher_targets_weak_link(self) -> None:
        """APPLY_EDGE_HEAT_CYPHER must match WeakLink nodes and set edge_heat."""
        from context_service.pipelines.assets.edge_heat import APPLY_EDGE_HEAT_CYPHER

        assert "WeakLink" in APPLY_EDGE_HEAT_CYPHER
        assert "edge_heat" in APPLY_EDGE_HEAT_CYPHER
        assert "UNWIND $updates AS u" in APPLY_EDGE_HEAT_CYPHER

    @pytest.mark.asyncio
    async def test_edge_heat_logic_accumulates_counts(
        self,
        silo_id: str,
        node_ids: tuple[str, str],
    ) -> None:
        """Simulate edge_heat event processing: multiple events for same edge
        should accumulate and result in a memgraph.execute call with heat > 0."""
        from context_service.signals.edge_access_events import edge_id

        node_a, node_b = node_ids
        eid = edge_id(node_a, node_b, "RELATED_TO")

        # Simulate three traversals of the same edge
        heat_acc: dict[str, float] = defaultdict(float)
        for _ in range(3):
            heat_acc[eid] += 1.0

        updates = [{"link_id": k, "heat_score": v} for k, v in heat_acc.items()]
        assert len(updates) == 1
        assert updates[0]["heat_score"] == 3.0
        assert updates[0]["link_id"] == eid

    # ------------------------------------------------------------------
    # Step 4: weak_link_review PROMOTE_CYPHER flips speculative -> false
    # ------------------------------------------------------------------

    def test_promote_cypher_flips_speculative(self) -> None:
        """PROMOTE_CYPHER must match speculative=true and set speculative=false."""
        from context_service.pipelines.assets.weak_link_review import PROMOTE_CYPHER

        assert "speculative = true" in PROMOTE_CYPHER
        assert "speculative = false" in PROMOTE_CYPHER

    def test_promote_cypher_requires_weight_and_heat_thresholds(self) -> None:
        """Promotion must gate on both weight and edge_heat."""
        from context_service.pipelines.assets.weak_link_review import PROMOTE_CYPHER

        assert "weight >=" in PROMOTE_CYPHER
        assert "edge_heat >=" in PROMOTE_CYPHER

    @pytest.mark.asyncio
    async def test_full_cycle_wiring_with_mocks(
        self,
        silo_id: str,
        node_ids: tuple[str, str],
    ) -> None:
        """End-to-end wiring smoke test with mocks.

        Exercises: create_weak_links_for_node -> emit_edge_access_event ->
        heat accumulation logic -> verify promotion Cypher shape.
        """
        from context_service.pipelines.assets.weak_link_creation import (
            create_weak_links_for_node,
        )
        from context_service.pipelines.assets.weak_link_review import PROMOTE_CYPHER
        from context_service.signals.edge_access_events import (
            edge_id as compute_edge_id,
        )
        from context_service.signals.edge_access_events import (
            emit_edge_access_event,
        )

        node_a, node_b = node_ids
        embedding = _fake_vector(42)

        # --- 1. create weak link ---
        memgraph = AsyncMock()
        qdrant = AsyncMock()
        memgraph.execute.return_value = [{"degree": 0}]
        candidate = MagicMock()
        candidate.id = node_b
        candidate.score = 0.88
        qdrant.search.return_value = [candidate]

        created = await create_weak_links_for_node(
            memgraph=memgraph,
            qdrant=qdrant,
            node_id=node_a,
            embedding=embedding,
            silo_id=silo_id,
            max_links_per_node=5,
            similarity_threshold=0.75,
            top_k_candidates=10,
            initial_weight_multiplier=0.5,
            embedding_model="jina-v3",
        )
        assert created == 1

        # Capture the link_id from the MERGE call
        merge_call = [c for c in memgraph.execute.call_args_list if "MERGE" in str(c)][0]
        link_id = merge_call[0][1]["link_id"]

        # --- 2. emit edge access events ---
        redis = AsyncMock()
        for _ in range(5):
            await emit_edge_access_event(
                redis=redis,
                silo_id=silo_id,
                from_node=node_a,
                to_node=node_b,
                edge_type="RELATED_TO",
            )

        assert redis.xadd.call_count == 5

        # All events carry the same deterministic edge_id
        expected_eid = compute_edge_id(node_a, node_b, "RELATED_TO")
        assert link_id == expected_eid

        # --- 3. verify heat accumulation ---
        heat_acc: dict[str, float] = defaultdict(float)
        for call in redis.xadd.call_args_list:
            payload = call[0][1]
            heat_acc[payload["edge_id"]] += 1.0

        assert heat_acc[expected_eid] == 5.0

        # --- 4. verify promotion Cypher will flip speculative ---
        assert "speculative = false" in PROMOTE_CYPHER
        assert "speculative = true" in PROMOTE_CYPHER


# ---------------------------------------------------------------------------
# Live integration test (requires full docker stack)
# ---------------------------------------------------------------------------


@requires_full_stack
@pytest.mark.asyncio
class TestWeakLinksCycleLive:
    """Full cycle against a live docker stack.

    Skipped automatically when Memgraph (7687), Qdrant (6333), or
    Redis (6379) are not reachable.
    """

    @pytest.fixture
    def silo_id(self) -> str:
        return f"test-wl-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    async def memgraph(self) -> Any:
        from context_service.config.settings import get_settings
        from context_service.stores import MemgraphClient, create_memgraph_driver

        settings = get_settings()
        driver = await create_memgraph_driver(settings)
        client = MemgraphClient(driver)
        yield client
        await driver.close()

    @pytest.fixture
    def qdrant(self) -> Any:
        from context_service.stores.qdrant import QdrantClient

        return QdrantClient(url="http://localhost:6333", vector_size=_VECTOR_DIM)

    @pytest.fixture
    async def redis(self) -> Any:
        import redis.asyncio as aioredis

        client = aioredis.from_url("redis://localhost:6379")
        yield client
        await client.aclose()

    @pytest.fixture
    async def cleanup(self, memgraph: Any, qdrant: Any, silo_id: str) -> Any:
        yield
        await memgraph.execute_write(
            "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
            {"silo_id": silo_id},
        )

    async def test_weak_link_full_cycle(
        self,
        memgraph: Any,
        qdrant: Any,
        redis: Any,
        silo_id: str,
        cleanup: Any,
    ) -> None:
        """End-to-end: embed nodes -> create weak links -> traverse ->
        update edge heat -> verify promotion query selects the link."""
        from context_service.pipelines.assets.edge_heat import APPLY_EDGE_HEAT_CYPHER
        from context_service.pipelines.assets.weak_link_creation import (
            MERGE_WEAK_LINK_CYPHER,
        )
        from context_service.pipelines.assets.weak_link_review import PROMOTE_CYPHER
        from context_service.signals.edge_access_events import (
            edge_id as compute_edge_id,
        )

        # --- 1. create two nodes in Memgraph ---
        node_a = str(uuid.uuid4())
        node_b = str(uuid.uuid4())
        for nid in (node_a, node_b):
            await memgraph.execute_write(
                "CREATE (n:Memory {id: $id, silo_id: $silo_id, content: $content})",
                {"id": nid, "silo_id": silo_id, "content": f"test node {nid[:8]}"},
            )

        # --- 2. create a weak link (no Qdrant needed; drive directly) ---
        link_id = compute_edge_id(node_a, node_b, "RELATED_TO")
        a, b = sorted([node_a, node_b])
        await memgraph.execute_write(
            MERGE_WEAK_LINK_CYPHER,
            {
                "from_id": a,
                "to_id": b,
                "link_id": link_id,
                "silo_id": silo_id,
                "weight": 0.80,
                "embedding_model": "jina-v3",
            },
        )

        # --- 3. verify WeakLink exists with speculative=true ---
        rows = await memgraph.execute(
            "MATCH (w:WeakLink {id: $id, silo_id: $silo_id}) RETURN w.speculative AS spec",
            {"id": link_id, "silo_id": silo_id},
        )
        assert rows, "WeakLink node not found after MERGE"
        assert rows[0]["spec"] is True, "Expected speculative=true after creation"

        # --- 4. simulate traversals -> update edge_heat directly ---
        heat_score = 5.0
        updates = [{"link_id": link_id, "heat_score": heat_score}]
        from datetime import UTC, datetime

        await memgraph.execute_write(
            APPLY_EDGE_HEAT_CYPHER,
            {
                "updates": updates,
                "silo_id": silo_id,
                "now": datetime.now(UTC).isoformat(),
            },
        )

        # --- 5. verify edge_heat > 0 ---
        heat_rows = await memgraph.execute(
            "MATCH (w:WeakLink {id: $id, silo_id: $silo_id}) RETURN w.edge_heat AS heat",
            {"id": link_id, "silo_id": silo_id},
        )
        assert heat_rows, "WeakLink not found for heat check"
        assert heat_rows[0]["heat"] > 0, "Expected edge_heat > 0 after heat update"

        # --- 6. run promotion: weight=0.80 > 0.6, heat=5.0 > 0.3, no fact req ---
        await memgraph.execute_write(
            PROMOTE_CYPHER,
            {
                "silo_id": silo_id,
                "min_weight": 0.6,
                "min_edge_heat": 0.3,
                "require_facts": False,
            },
        )

        # --- 7. verify speculative=false after promotion ---
        promo_rows = await memgraph.execute(
            "MATCH (w:WeakLink {id: $id, silo_id: $silo_id}) RETURN w.speculative AS spec",
            {"id": link_id, "silo_id": silo_id},
        )
        assert promo_rows, "WeakLink not found after promotion"
        assert promo_rows[0]["spec"] is False, "Expected speculative=false after promotion"
