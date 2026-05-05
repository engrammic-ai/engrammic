"""Integration tests for hybrid Postgres+Memgraph storage.

Covers:
1. Saga write path: steps in Postgres, summary projection in Memgraph.
2. Saga compensation: Memgraph failure rolls back Postgres row.
3. context_recall with include_steps: steps fetched from Postgres and attached.
4. Consolidation: canonical conclusion created with CONSOLIDATES edges.

Requires a live Postgres + Memgraph stack. Skipped automatically when either
service is unreachable.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.custodian.consolidation import ConclusionConsolidator
from context_service.engine.chain_saga import ChainSagaWriter
from context_service.engine.postgres_store import PostgresStore
from context_service.models.inference import ChainStep

# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------


def _check_postgres_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 5432))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


def _is_memgraph_up() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 7687))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


postgres_available = pytest.mark.skipif(
    not _check_postgres_available(),
    reason="Postgres not running on localhost:5432",
)

hybrid_available = pytest.mark.skipif(
    not (_check_postgres_available() and _is_memgraph_up()),
    reason="Postgres or Memgraph not running",
)


async def _ensure_pg_schema() -> None:
    """Create Postgres tables if they do not exist.

    Uses checkfirst=True so it is a no-op against a database that has already
    been migrated via Alembic.  Each caller runs inside its own event loop so
    we dispose the engine afterwards to avoid cross-loop pool reuse.
    """
    from context_service.db.postgres import Base, close_postgres, init_postgres
    from context_service.models.postgres.reasoning import (  # noqa: F401
        OrphanedChains,
        ReasoningChainSteps,
    )

    engine = await init_postgres()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    await close_postgres()


@pytest.fixture
async def pg_schema() -> None:
    """Ensure Postgres schema exists for one test function."""
    if not _check_postgres_available():
        return
    await _ensure_pg_schema()


@pytest.fixture
async def pg_test_silo(pg_schema: None) -> AsyncGenerator[uuid.UUID, None]:
    """Insert test rows into org_preferences + silo_config; yield silo_id.

    Cleans up after the test.  Both tables exist only when the hybrid storage
    migration has run (or was created by _ensure_pg_schema above).
    """
    from sqlalchemy import text

    from context_service.db.postgres import close_postgres, get_session, init_postgres

    await init_postgres()
    silo_id = uuid.uuid4()
    org_id = uuid.uuid4()

    async with get_session() as session:
        await session.execute(
            text("INSERT INTO org_preferences (org_id) VALUES (:org_id) ON CONFLICT DO NOTHING"),
            {"org_id": org_id},
        )
        await session.execute(
            text(
                "INSERT INTO silo_config (silo_id, org_id, name)"
                " VALUES (:silo_id, :org_id, :name)"
                " ON CONFLICT DO NOTHING"
            ),
            {"silo_id": silo_id, "org_id": org_id, "name": "test-silo"},
        )

    yield silo_id

    async with get_session() as session:
        # Delete child rows first to avoid FK violations on cleanup.
        await session.execute(
            text("DELETE FROM reasoning_chain_steps WHERE silo_id = :silo_id"),
            {"silo_id": silo_id},
        )
        await session.execute(
            text("DELETE FROM orphaned_chains WHERE silo_id = :silo_id"),
            {"silo_id": silo_id},
        )
        await session.execute(
            text("DELETE FROM silo_config WHERE silo_id = :silo_id"),
            {"silo_id": silo_id},
        )
        await session.execute(
            text("DELETE FROM org_preferences WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
    await close_postgres()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_steps(n: int = 2) -> list[ChainStep]:
    return [
        ChainStep(
            step_index=i,
            operation="deduction",
            conclusion=f"step {i} conclusion",
            confidence=0.75 + i * 0.05,
            premise_refs=[f"ref-{i}"],
        )
        for i in range(n)
    ]


def _make_memgraph_stub() -> AsyncMock:
    """Return a mock that satisfies the MemgraphStore interface used by ChainSagaWriter."""
    stub = AsyncMock()
    stub.upsert_reasoning_chain = AsyncMock(return_value=None)
    return stub


# ---------------------------------------------------------------------------
# Test: Saga write path
# ---------------------------------------------------------------------------


@postgres_available
@pytest.mark.integration
class TestSagaWritePath:
    """Verify steps land in Postgres and summary is projected to Memgraph."""

    @pytest.fixture
    def chain_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.fixture
    def steps(self) -> list[ChainStep]:
        return _make_steps(3)

    @pytest.fixture
    def memgraph_stub(self) -> AsyncMock:
        return _make_memgraph_stub()

    @pytest.fixture
    def postgres_store(self) -> PostgresStore:
        return PostgresStore()

    async def test_steps_written_to_postgres(
        self,
        chain_id: uuid.UUID,
        pg_test_silo: uuid.UUID,
        steps: list[ChainStep],
        memgraph_stub: AsyncMock,
        postgres_store: PostgresStore,
    ) -> None:
        writer = ChainSagaWriter(postgres_store, memgraph_stub)
        await writer.write_chain(
            chain_id=chain_id,
            silo_id=pg_test_silo,
            steps=steps,
            produced_by_model="test-model",
            produced_by_agent_id="test-agent",
            conclusion="test conclusion",
            evidence_used=["ev-1", "ev-2"],
        )

        stored = await postgres_store.get_chain_steps(chain_id)
        assert stored is not None
        assert len(stored) == len(steps)
        assert stored[0]["conclusion"] == steps[0].conclusion

        # Cleanup
        await postgres_store.delete_chain_steps(chain_id)

    async def test_memgraph_upsert_called_with_conclusion(
        self,
        chain_id: uuid.UUID,
        pg_test_silo: uuid.UUID,
        steps: list[ChainStep],
        memgraph_stub: AsyncMock,
        postgres_store: PostgresStore,
    ) -> None:
        writer = ChainSagaWriter(postgres_store, memgraph_stub)
        conclusion_text = "the final answer is 42"
        await writer.write_chain(
            chain_id=chain_id,
            silo_id=pg_test_silo,
            steps=steps,
            produced_by_model="test-model",
            produced_by_agent_id="test-agent",
            conclusion=conclusion_text,
            evidence_used=["ev-a"],
        )

        memgraph_stub.upsert_reasoning_chain.assert_awaited_once()
        call_kwargs = memgraph_stub.upsert_reasoning_chain.call_args.kwargs
        assert call_kwargs["conclusion"] == conclusion_text
        assert call_kwargs["chain_id"] == str(chain_id)
        assert call_kwargs["silo_id"] == str(pg_test_silo)

        # Cleanup
        await postgres_store.delete_chain_steps(chain_id)

    async def test_evidence_used_propagated(
        self,
        chain_id: uuid.UUID,
        pg_test_silo: uuid.UUID,
        steps: list[ChainStep],
        memgraph_stub: AsyncMock,
        postgres_store: PostgresStore,
    ) -> None:
        writer = ChainSagaWriter(postgres_store, memgraph_stub)
        evidence = ["ev-x", "ev-y", "ev-z"]
        await writer.write_chain(
            chain_id=chain_id,
            silo_id=pg_test_silo,
            steps=steps,
            produced_by_model="test-model",
            produced_by_agent_id="test-agent",
            evidence_used=evidence,
        )

        call_kwargs = memgraph_stub.upsert_reasoning_chain.call_args.kwargs
        # evidence_used items should appear in all_premise_refs
        for ev in evidence:
            assert ev in call_kwargs["all_premise_refs"]

        # Cleanup
        await postgres_store.delete_chain_steps(chain_id)


# ---------------------------------------------------------------------------
# Test: Saga compensation
# ---------------------------------------------------------------------------


@postgres_available
@pytest.mark.integration
class TestSagaCompensation:
    """Verify Postgres row is deleted when Memgraph fails."""

    @pytest.fixture(autouse=True)
    async def _setup_schema(self, pg_schema: None) -> None:  # noqa: PT004
        pass

    @pytest.fixture
    def postgres_store(self) -> PostgresStore:
        return PostgresStore()

    async def test_postgres_rolled_back_on_memgraph_failure(
        self, postgres_store: PostgresStore, pg_test_silo: uuid.UUID
    ) -> None:
        chain_id = uuid.uuid4()
        silo_id = pg_test_silo
        steps = _make_steps(2)

        failing_mg = AsyncMock()
        failing_mg.upsert_reasoning_chain = AsyncMock(
            side_effect=RuntimeError("memgraph unavailable")
        )

        writer = ChainSagaWriter(postgres_store, failing_mg)

        with pytest.raises(RuntimeError, match="memgraph unavailable"):
            await writer.write_chain(
                chain_id=chain_id,
                silo_id=silo_id,
                steps=steps,
                produced_by_model="test-model",
                produced_by_agent_id="test-agent",
            )

        # Compensation must have deleted the Postgres row.
        stored = await postgres_store.get_chain_steps(chain_id)
        assert stored is None

    async def test_orphaned_chain_added_when_compensation_fails(
        self, postgres_store: PostgresStore, pg_test_silo: uuid.UUID
    ) -> None:
        chain_id = uuid.uuid4()
        silo_id = pg_test_silo
        steps = _make_steps(1)

        failing_mg = AsyncMock()
        failing_mg.upsert_reasoning_chain = AsyncMock(side_effect=RuntimeError("memgraph down"))

        # Patch PostgresStore.delete_chain_steps to always fail so compensation
        # exhausts all retries and falls back to the dead-letter table.
        with (
            patch.object(
                postgres_store,
                "delete_chain_steps",
                AsyncMock(side_effect=RuntimeError("pg delete failed")),
            ),
            pytest.raises(RuntimeError, match="memgraph down"),
        ):
            await writer_for(postgres_store, failing_mg).write_chain(
                chain_id=chain_id,
                silo_id=silo_id,
                steps=steps,
                produced_by_model="test-model",
                produced_by_agent_id="test-agent",
            )

        # Chain should now be in the orphaned dead-letter table.
        from sqlalchemy import select

        from context_service.db.postgres import get_session
        from context_service.models.postgres.reasoning import OrphanedChains

        async with get_session() as session:
            stmt = select(OrphanedChains).where(OrphanedChains.chain_id == chain_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        assert row is not None
        assert row.retry_count >= 1

        # Cleanup orphan row
        from sqlalchemy import delete as sa_delete

        async with get_session() as session:
            await session.execute(
                sa_delete(OrphanedChains).where(OrphanedChains.chain_id == chain_id)
            )


def writer_for(pg: PostgresStore, mg: Any) -> ChainSagaWriter:
    return ChainSagaWriter(pg, mg)


# ---------------------------------------------------------------------------
# Test: context_recall with include_steps
# ---------------------------------------------------------------------------


@postgres_available
@pytest.mark.integration
class TestContextRecallIncludeSteps:
    """Verify include_steps fetches step data from Postgres and attaches to nodes."""

    @pytest.fixture(autouse=True)
    async def _setup_schema(self, pg_schema: None) -> None:  # noqa: PT004
        pass

    @pytest.fixture
    def postgres_store(self) -> PostgresStore:
        return PostgresStore()

    async def test_include_steps_attaches_steps_to_intelligence_node(
        self, postgres_store: PostgresStore, pg_test_silo: uuid.UUID
    ) -> None:
        from context_service.mcp.tools.context_recall import _context_recall

        chain_id = uuid.uuid4()
        steps = _make_steps(3)
        steps_data = [s.model_dump(mode="json") for s in steps]

        # Write steps directly to Postgres.
        await postgres_store.upsert_chain_steps(chain_id, pg_test_silo, steps_data)

        chain_id_str = str(chain_id)

        # Mock _context_get to return a node referencing our chain.
        mock_node = {
            "node_id": chain_id_str,
            "layer": "intelligence",
            "label": "ReasoningChain",
        }
        mock_get_response: dict[str, Any] = {"nodes": [mock_node]}

        # _fetch_chain_steps is called internally with just chain_ids; delegate
        # to the real postgres_store by patching the function.
        async def _fake_fetch(
            chain_ids: list[str], postgres_store: Any = None
        ) -> dict[str, list[dict[str, Any]]]:
            uuids = [uuid.UUID(cid) for cid in chain_ids]
            from context_service.engine.postgres_store import PostgresStore as PGS

            pg = PGS()
            steps_map = await pg.get_chain_steps_batch(uuids)
            return {str(k): v for k, v in steps_map.items() if v}

        with (
            patch(
                "context_service.mcp.tools.context_recall._context_get",
                AsyncMock(return_value=mock_get_response),
            ),
            patch(
                "context_service.mcp.tools.context_recall._fetch_chain_steps",
                _fake_fetch,
            ),
        ):
            response = await _context_recall(
                silo_id=str(pg_test_silo),
                node_ids=[chain_id_str],
                include_steps=True,
            )

        nodes = response.get("nodes", [])
        assert len(nodes) == 1
        result_node = nodes[0]
        assert "steps" in result_node
        assert len(result_node["steps"]) == len(steps)
        assert result_node["steps"][0]["conclusion"] == steps[0].conclusion

        # Cleanup
        await postgres_store.delete_chain_steps(chain_id)

    async def test_include_steps_false_does_not_attach_steps(
        self, postgres_store: PostgresStore, pg_test_silo: uuid.UUID
    ) -> None:
        from context_service.mcp.tools.context_recall import _context_recall

        chain_id = uuid.uuid4()
        steps = _make_steps(2)
        await postgres_store.upsert_chain_steps(
            chain_id, pg_test_silo, [s.model_dump(mode="json") for s in steps]
        )

        mock_node = {
            "node_id": str(chain_id),
            "layer": "intelligence",
            "label": "ReasoningChain",
        }
        mock_get_response: dict[str, Any] = {"nodes": [mock_node]}

        with patch(
            "context_service.mcp.tools.context_recall._context_get",
            AsyncMock(return_value=mock_get_response),
        ):
            response = await _context_recall(
                silo_id=str(pg_test_silo),
                node_ids=[str(chain_id)],
                include_steps=False,
            )

        nodes = response.get("nodes", [])
        assert "steps" not in nodes[0]

        # Cleanup
        await postgres_store.delete_chain_steps(chain_id)

    async def test_non_intelligence_nodes_not_hydrated(self, postgres_store: PostgresStore) -> None:
        from context_service.mcp.tools.context_recall import _context_recall

        knowledge_node_id = str(uuid.uuid4())
        mock_node = {
            "node_id": knowledge_node_id,
            "layer": "knowledge",
            "label": "Claim",
        }
        mock_get_response: dict[str, Any] = {"nodes": [mock_node]}

        with patch(
            "context_service.mcp.tools.context_recall._context_get",
            AsyncMock(return_value=mock_get_response),
        ):
            response = await _context_recall(
                silo_id=str(uuid.uuid4()),
                node_ids=[knowledge_node_id],
                include_steps=True,
            )

        nodes = response.get("nodes", [])
        assert "steps" not in nodes[0]


# ---------------------------------------------------------------------------
# Test: Consolidation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConsolidation:
    """Verify ConclusionConsolidator creates a canonical with CONSOLIDATES edges."""

    def _make_mock_store(self, conclusions: list[dict[str, Any]]) -> AsyncMock:
        store = AsyncMock()
        store.get_conclusions_by_hash = AsyncMock(return_value=conclusions)
        store.upsert_conclusion = AsyncMock(return_value=None)
        store.create_consolidates_edge = AsyncMock(return_value=None)
        store.mark_conclusion_consolidated = AsyncMock(return_value=None)
        store.find_orphaned_active_conclusions = AsyncMock(return_value=[])
        return store

    def _make_redis_stub(self) -> Any:
        """Return a Redis mock that supports async context manager locking."""
        lock = MagicMock()
        lock.__aenter__ = AsyncMock(return_value=None)
        lock.__aexit__ = AsyncMock(return_value=None)
        redis = MagicMock()
        redis.lock = MagicMock(return_value=lock)
        return redis

    async def test_consolidation_creates_canonical(self) -> None:
        silo_id = str(uuid.uuid4())
        qch = "hash-abc-123"

        conclusions = [
            {"id": str(uuid.uuid4()), "content": "answer A", "confidence": 0.8, "status": "active"},
            {"id": str(uuid.uuid4()), "content": "answer B", "confidence": 0.9, "status": "active"},
        ]

        store = self._make_mock_store(conclusions)
        redis = self._make_redis_stub()

        consolidator = ConclusionConsolidator(store, redis)
        canonical_id = await consolidator.consolidate_by_hash(silo_id, qch)

        assert canonical_id is not None
        store.upsert_conclusion.assert_awaited_once()
        call_kwargs = store.upsert_conclusion.call_args.kwargs
        assert call_kwargs["silo_id"] == silo_id
        assert call_kwargs["query_context_hash"] == qch
        # Confidence should be boosted above the average.
        avg = (0.8 + 0.9) / 2
        assert call_kwargs["confidence"] > avg

    async def test_consolidation_creates_consolidates_edges(self) -> None:
        silo_id = str(uuid.uuid4())
        qch = "hash-edges-456"
        ids = [str(uuid.uuid4()) for _ in range(3)]
        conclusions = [
            {
                "id": ids[i],
                "content": f"answer {i}",
                "confidence": 0.7 + i * 0.05,
                "status": "active",
            }
            for i in range(3)
        ]

        store = self._make_mock_store(conclusions)
        redis = self._make_redis_stub()

        consolidator = ConclusionConsolidator(store, redis)
        canonical_id = await consolidator.consolidate_by_hash(silo_id, qch)

        assert canonical_id is not None
        assert store.create_consolidates_edge.await_count == len(conclusions)
        # Every original should be marked consolidated.
        assert store.mark_conclusion_consolidated.await_count == len(conclusions)

    async def test_consolidation_skipped_when_already_consolidated(self) -> None:
        silo_id = str(uuid.uuid4())
        qch = "hash-idempotent-789"
        conclusions = [
            {"id": str(uuid.uuid4()), "content": "a", "confidence": 0.8, "status": "consolidated"},
            {"id": str(uuid.uuid4()), "content": "b", "confidence": 0.9, "status": "active"},
        ]

        store = self._make_mock_store(conclusions)
        redis = self._make_redis_stub()

        consolidator = ConclusionConsolidator(store, redis)
        result = await consolidator.consolidate_by_hash(silo_id, qch)

        assert result is None
        store.upsert_conclusion.assert_not_awaited()

    async def test_consolidation_skipped_when_fewer_than_two_active(self) -> None:
        silo_id = str(uuid.uuid4())
        qch = "hash-single-active"
        conclusions = [
            {"id": str(uuid.uuid4()), "content": "only one", "confidence": 0.8, "status": "active"},
        ]

        store = self._make_mock_store(conclusions)
        redis = self._make_redis_stub()

        consolidator = ConclusionConsolidator(store, redis)
        result = await consolidator.consolidate_by_hash(silo_id, qch)

        assert result is None
        store.upsert_conclusion.assert_not_awaited()

    async def test_repair_orphaned_consolidations(self) -> None:
        silo_id = str(uuid.uuid4())
        orphan_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        store = self._make_mock_store([])
        store.find_orphaned_active_conclusions = AsyncMock(return_value=orphan_ids)
        redis = self._make_redis_stub()

        consolidator = ConclusionConsolidator(store, redis)
        repaired = await consolidator.repair_orphaned_consolidations(silo_id)

        assert repaired == len(orphan_ids)
        assert store.mark_conclusion_consolidated.await_count == len(orphan_ids)
