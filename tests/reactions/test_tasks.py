"""Unit tests for reaction task handlers.

All tests use InMemoryBroker so no Redis is required. Service dependencies
(get_context_service, build_embedding_service, cascade_staleness,
ConsolidationWorker) are mocked so handlers execute in isolation.

Integration note
----------------
The emit->process end-to-end flow is validated in
test_emit_to_process_integration below using InMemoryBroker, which executes
tasks inline (no worker process needed).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from taskiq import InMemoryBroker

from context_service.reactions.events import ReactionEvent, ReactionEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(node_id: str, content: str = "test content") -> MagicMock:
    node = MagicMock()
    node.id = uuid.UUID(node_id)
    node.content = content
    node.type = "Memory"
    return node


def _patch_ctx_svc(mock_context_service: MagicMock) -> Any:
    """Context manager: patch get_context_service to return mock_context_service."""
    return patch(
        "context_service.mcp.server.get_context_service",
        return_value=mock_context_service,
    )


# ---------------------------------------------------------------------------
# compute_embedding
# ---------------------------------------------------------------------------


class TestComputeEmbeddingTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        node_id = str(uuid.uuid4())
        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            result = await task.kiq(node_id=node_id, silo_id="s1")

        # Task should complete without raising
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_op_when_node_not_found(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        mock_graph_store.get_node = AsyncMock(return_value=None)
        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with _patch_ctx_svc(mock_context_service):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        mock_graph_store.get_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_op_when_node_has_no_content(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        node = _make_node(node_id, content="")
        mock_graph_store.get_node = AsyncMock(return_value=node)

        embedder = AsyncMock()
        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.embeddings.build_embedding_service", return_value=embedder),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        embedder.embed_single.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_embeds_node_content(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        node = _make_node(node_id, content="some content to embed")
        mock_graph_store.get_node = AsyncMock(return_value=node)

        embedder = MagicMock()
        embedder.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])
        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch(
                "context_service.embeddings.build_embedding_service",
                return_value=embedder,
            ),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        embedder.embed_single.assert_awaited_once_with("some content to embed")


# ---------------------------------------------------------------------------
# update_heat
# ---------------------------------------------------------------------------


class TestUpdateHeatTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_HEAT)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_executes_cypher_write(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        mock_graph_store.execute_write = AsyncMock(return_value=[{"heat_score": 3.0}])
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_HEAT)
        assert task is not None

        with _patch_ctx_svc(mock_context_service):
            await task.kiq(node_id=node_id, silo_id="s1", delta=1.0)

        mock_graph_store.execute_write.assert_awaited_once()
        call_args = mock_graph_store.execute_write.call_args
        params = call_args[0][1]
        assert params["node_id"] == node_id
        assert params["silo_id"] == "s1"
        assert params["delta"] == 1.0

    @pytest.mark.asyncio
    async def test_uses_default_delta_of_one(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        mock_graph_store.execute_write = AsyncMock(return_value=[])
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_HEAT)
        assert task is not None

        with _patch_ctx_svc(mock_context_service):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        call_args = mock_graph_store.execute_write.call_args
        assert call_args[0][1]["delta"] == 1.0

    @pytest.mark.asyncio
    async def test_accepts_custom_delta(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        mock_graph_store.execute_write = AsyncMock(return_value=[{"heat_score": 5.5}])
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_HEAT)
        assert task is not None

        with _patch_ctx_svc(mock_context_service):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1", delta=0.5)

        params = mock_graph_store.execute_write.call_args[0][1]
        assert params["delta"] == 0.5


# ---------------------------------------------------------------------------
# update_cluster_membership (stub)
# ---------------------------------------------------------------------------


class TestUpdateClusterMembershipTask:
    @pytest.mark.asyncio
    async def test_stub_completes_without_error(self, in_memory_broker: InMemoryBroker) -> None:
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None
        # Phase 8a stub: no external calls, just completes
        await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")


# ---------------------------------------------------------------------------
# cascade_staleness
# ---------------------------------------------------------------------------


class TestCascadeStalenessTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.CASCADE_STALENESS)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_delegates_to_cascade_staleness(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        mock_cascade = AsyncMock(return_value=3)
        task = in_memory_broker.find_task(ReactionEventType.CASCADE_STALENESS)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.transactions.cascade_staleness", mock_cascade),
        ):
            await task.kiq(node_id=node_id, silo_id="s1", depth=2)

        mock_cascade.assert_awaited_once_with(
            mock_context_service.graph_store,
            node_id=node_id,
            silo_id="s1",
            depth=2,
        )

    @pytest.mark.asyncio
    async def test_uses_default_depth_of_one(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        mock_cascade = AsyncMock(return_value=0)
        task = in_memory_broker.find_task(ReactionEventType.CASCADE_STALENESS)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.transactions.cascade_staleness", mock_cascade),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        call_kwargs = mock_cascade.call_args[1]
        assert call_kwargs["depth"] == 1


# ---------------------------------------------------------------------------
# flag_contradiction
# ---------------------------------------------------------------------------


class TestFlagContradictionTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.FLAG_CONTRADICTION)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_sets_conflict_status_unresolved(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        task = in_memory_broker.find_task(ReactionEventType.FLAG_CONTRADICTION)
        assert task is not None

        with _patch_ctx_svc(mock_context_service):
            await task.kiq(node_id=node_id, silo_id="s1")

        mock_graph_store.execute_write.assert_awaited_once()
        cypher, params = mock_graph_store.execute_write.call_args[0]
        assert "conflict_status" in cypher
        assert "'unresolved'" in cypher
        assert params["node_id"] == node_id

    @pytest.mark.asyncio
    async def test_queues_consolidate_when_conflict_node_provided(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        conflict_node_id = str(uuid.uuid4())
        task = in_memory_broker.find_task(ReactionEventType.FLAG_CONTRADICTION)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(
                node_id=node_id,
                silo_id="s1",
                conflict_node_id=conflict_node_id,
            )

        mock_emit.assert_awaited_once()
        emitted_event: ReactionEvent = mock_emit.call_args[0][0]
        assert emitted_event.event_type == ReactionEventType.CONSOLIDATE
        assert emitted_event.node_id == node_id
        assert emitted_event.payload["conflict_node_id"] == conflict_node_id

    @pytest.mark.asyncio
    async def test_does_not_queue_consolidate_without_conflict_node(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.FLAG_CONTRADICTION)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        mock_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# consolidate
# ---------------------------------------------------------------------------


@dataclass
class _ConsolidationResult:
    action: str
    rationale: str


class TestConsolidateTask:
    @pytest.mark.asyncio
    async def test_skips_when_conflict_node_id_missing(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.CONSOLIDATE)
        assert task is not None
        # Should not raise even without services
        await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.CONSOLIDATE)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(
                node_id=str(uuid.uuid4()),
                silo_id="s1",
                conflict_node_id=str(uuid.uuid4()),
            )

    @pytest.mark.asyncio
    async def test_calls_consolidation_worker(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        node_id = str(uuid.uuid4())
        conflict_node_id = str(uuid.uuid4())
        mock_result = _ConsolidationResult(action="supersede", rationale="a is newer")

        mock_worker = MagicMock()
        mock_worker.process_conflict = AsyncMock(return_value=mock_result)

        task = in_memory_broker.find_task(ReactionEventType.CONSOLIDATE)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch(
                "context_service.sage.consolidation.ConsolidationWorker",
                return_value=mock_worker,
            ),
        ):
            await task.kiq(
                node_id=node_id,
                silo_id="s1",
                conflict_node_id=conflict_node_id,
            )

        mock_worker.process_conflict.assert_awaited_once_with(
            store=mock_context_service.graph_store,
            node_a_id=node_id,
            node_b_id=conflict_node_id,
            silo_id="s1",
        )


# ---------------------------------------------------------------------------
# check_synthesis (stub)
# ---------------------------------------------------------------------------


class TestCheckSynthesisTask:
    @pytest.mark.asyncio
    async def test_stub_completes_without_error(self, in_memory_broker: InMemoryBroker) -> None:
        task = in_memory_broker.find_task(ReactionEventType.CHECK_SYNTHESIS)
        assert task is not None
        await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")


# ---------------------------------------------------------------------------
# propagate_confidence (stub)
# ---------------------------------------------------------------------------


class TestPropagateConfidenceTask:
    @pytest.mark.asyncio
    async def test_stub_completes_without_error(self, in_memory_broker: InMemoryBroker) -> None:
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None
        await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")


# ---------------------------------------------------------------------------
# Silo isolation
# ---------------------------------------------------------------------------


class TestSiloIsolation:
    @pytest.mark.asyncio
    async def test_different_silos_use_separate_stores(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        """Handlers receive the silo_id from the event, not from a shared state."""
        store_a = AsyncMock()
        store_a.execute_write = AsyncMock(return_value=[])

        store_b = AsyncMock()
        store_b.execute_write = AsyncMock(return_value=[])

        ctx_a = MagicMock()
        ctx_a.graph_store = store_a

        ctx_b = MagicMock()
        ctx_b.graph_store = store_b

        node_id_a = str(uuid.uuid4())
        node_id_b = str(uuid.uuid4())

        task = in_memory_broker.find_task(ReactionEventType.UPDATE_HEAT)
        assert task is not None

        # Execute task for silo-A
        with patch("context_service.mcp.server.get_context_service", return_value=ctx_a):
            await task.kiq(node_id=node_id_a, silo_id="silo-alpha")

        # Execute task for silo-B
        with patch("context_service.mcp.server.get_context_service", return_value=ctx_b):
            await task.kiq(node_id=node_id_b, silo_id="silo-beta")

        # Each store received exactly one write with its own silo_id
        assert store_a.execute_write.await_count == 1
        params_a = store_a.execute_write.call_args[0][1]
        assert params_a["silo_id"] == "silo-alpha"
        assert params_a["node_id"] == node_id_a

        assert store_b.execute_write.await_count == 1
        params_b = store_b.execute_write.call_args[0][1]
        assert params_b["silo_id"] == "silo-beta"
        assert params_b["node_id"] == node_id_b


# ---------------------------------------------------------------------------
# Integration: emit -> process flow (InMemoryBroker, no Redis)
# ---------------------------------------------------------------------------


class TestEmitToProcessIntegration:
    @pytest.mark.asyncio
    async def test_emit_update_heat_processes_end_to_end(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """End-to-end: emit_reaction -> broker task executes -> store called."""
        mock_graph_store.execute_write = AsyncMock(return_value=[{"heat_score": 1.0}])
        node_id = str(uuid.uuid4())

        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=node_id,
            silo_id="integration-silo",
            payload={"delta": 1.0},
        )

        # Patch get_broker at the broker module (where it is defined); emit_reaction
        # imports it locally from there, so this is the correct patch target.
        with (
            patch("context_service.reactions.broker.get_broker", return_value=in_memory_broker),
            patch("context_service.mcp.server.get_context_service", return_value=mock_context_service),
        ):
            from context_service.reactions.events import emit_reaction

            await emit_reaction(event)

        mock_graph_store.execute_write.assert_awaited_once()
        params = mock_graph_store.execute_write.call_args[0][1]
        assert params["node_id"] == node_id
        assert params["silo_id"] == "integration-silo"

    @pytest.mark.asyncio
    async def test_emit_flag_contradiction_chains_to_consolidate(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
    ) -> None:
        """Emit flag_contradiction with conflict_node_id -> consolidate event is queued."""
        node_id = str(uuid.uuid4())
        conflict_node_id = str(uuid.uuid4())

        consolidate_calls: list[ReactionEvent] = []

        async def capture_emit(ev: ReactionEvent) -> None:
            if ev.event_type == ReactionEventType.CONSOLIDATE:
                consolidate_calls.append(ev)

        with (
            patch("context_service.mcp.server.get_context_service", return_value=mock_context_service),
            patch("context_service.reactions.events.emit_reaction", side_effect=capture_emit),
        ):
            task = in_memory_broker.find_task(ReactionEventType.FLAG_CONTRADICTION)
            assert task is not None
            await task.kiq(
                node_id=node_id,
                silo_id="chain-silo",
                conflict_node_id=conflict_node_id,
            )

        assert len(consolidate_calls) == 1
        assert consolidate_calls[0].node_id == node_id
        assert consolidate_calls[0].payload["conflict_node_id"] == conflict_node_id
