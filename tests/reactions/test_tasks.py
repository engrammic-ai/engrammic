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
from context_service.sage.transactions import SYNTHESIS_THRESHOLD

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

        mock_vector_store = AsyncMock()
        mock_vector_store.exists = AsyncMock(return_value=False)
        mock_context_service.vector_store = mock_vector_store

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

    @pytest.mark.asyncio
    async def test_upserts_vector_to_qdrant(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """Verify compute_embedding calls vector_store.upsert with correct params."""
        node_id = str(uuid.uuid4())
        node = _make_node(node_id, content="content for qdrant")
        mock_graph_store.get_node = AsyncMock(return_value=node)

        mock_vector_store = AsyncMock()
        mock_vector_store.exists = AsyncMock(return_value=False)
        mock_context_service.vector_store = mock_vector_store

        vector = [0.1] * 768
        embedder = MagicMock()
        embedder.embed_single = AsyncMock(return_value=vector)

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

        mock_vector_store.upsert.assert_awaited_once_with(
            node_id=node_id,
            vector=vector,
            payload={"type": "Memory"},
            silo_id="s1",
        )

    @pytest.mark.asyncio
    async def test_skips_embedding_when_already_embedded(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """compute_embedding_task returns early if the vector already exists in Qdrant."""
        node_id = str(uuid.uuid4())
        node = _make_node(node_id, content="some content")
        mock_graph_store.get_node = AsyncMock(return_value=node)

        mock_vector_store = AsyncMock()
        mock_vector_store.exists = AsyncMock(return_value=True)
        mock_context_service.vector_store = mock_vector_store

        embedder = AsyncMock()
        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.embeddings.build_embedding_service", return_value=embedder),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        embedder.embed_single.assert_not_awaited()
        mock_vector_store.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proceeds_when_not_yet_embedded(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """compute_embedding_task embeds and upserts when no existing vector is found."""
        node_id = str(uuid.uuid4())
        node = _make_node(node_id, content="content to embed")
        mock_graph_store.get_node = AsyncMock(return_value=node)

        mock_vector_store = AsyncMock()
        mock_vector_store.exists = AsyncMock(return_value=False)
        mock_context_service.vector_store = mock_vector_store

        vector = [0.5] * 768
        embedder = MagicMock()
        embedder.embed_single = AsyncMock(return_value=vector)

        task = in_memory_broker.find_task(ReactionEventType.COMPUTE_EMBEDDING)
        assert task is not None

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.embeddings.build_embedding_service", return_value=embedder),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        embedder.embed_single.assert_awaited_once_with("content to embed")
        mock_vector_store.upsert.assert_awaited_once()


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
# update_cluster_membership
# ---------------------------------------------------------------------------


class TestUpdateClusterMembershipTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_no_op_when_no_cluster_found(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """No cluster_id in payload and empty membership query -> silent no-op."""
        mock_graph_store.execute_query = AsyncMock(return_value=[])
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_cluster_id_hint_emits_check_synthesis_when_threshold_met(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """cluster_id in payload skips membership query; emits CHECK_SYNTHESIS at threshold."""
        node_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        # Only the count query is executed when cluster_id hint is provided
        mock_graph_store.execute_query = AsyncMock(
            return_value=[{"member_count": SYNTHESIS_THRESHOLD}]
        )
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(node_id=node_id, silo_id="s1", cluster_id=cluster_id)

        mock_emit.assert_awaited_once()
        emitted_event: ReactionEvent = mock_emit.call_args[0][0]
        assert emitted_event.event_type == ReactionEventType.CHECK_SYNTHESIS
        assert emitted_event.node_id == node_id
        assert emitted_event.payload["cluster_id"] == cluster_id

    @pytest.mark.asyncio
    async def test_with_cluster_id_hint_no_emit_below_threshold(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """cluster_id provided but member count below threshold -> no synthesis event."""
        mock_graph_store.execute_query = AsyncMock(
            return_value=[{"member_count": SYNTHESIS_THRESHOLD - 1}]
        )
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(
                node_id=str(uuid.uuid4()),
                silo_id="s1",
                cluster_id=str(uuid.uuid4()),
            )

        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_cluster_id_hint_queries_membership_then_count(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """No cluster_id hint: first query resolves membership, second counts members."""
        node_id = str(uuid.uuid4())
        cluster_id = str(uuid.uuid4())
        # First call = MEMBER_OF lookup, second = count query
        mock_graph_store.execute_query = AsyncMock(
            side_effect=[
                [{"cluster_id": cluster_id}],
                [{"member_count": SYNTHESIS_THRESHOLD}],
            ]
        )
        task = in_memory_broker.find_task(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP)
        assert task is not None

        mock_emit = AsyncMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.reactions.events.emit_reaction", mock_emit),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        assert mock_graph_store.execute_query.await_count == 2
        first_query_cypher = mock_graph_store.execute_query.call_args_list[0][0][0]
        assert "MEMBER_OF" in first_query_cypher

        mock_emit.assert_awaited_once()
        emitted_event: ReactionEvent = mock_emit.call_args[0][0]
        assert emitted_event.event_type == ReactionEventType.CHECK_SYNTHESIS


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
# propagate_confidence
# ---------------------------------------------------------------------------


class TestPropagateConfidenceTask:
    @pytest.mark.asyncio
    async def test_no_op_when_services_not_configured(
        self, in_memory_broker: InMemoryBroker
    ) -> None:
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None

        with patch(
            "context_service.mcp.server.get_context_service",
            side_effect=RuntimeError("not configured"),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

    @pytest.mark.asyncio
    async def test_no_op_when_no_neighborhood_found(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        mock_graph_store.execute_query = AsyncMock(return_value=[])
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None

        mock_propagate = MagicMock()
        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.epistemology.propagate_incremental", mock_propagate),
        ):
            await task.kiq(node_id=str(uuid.uuid4()), silo_id="s1")

        mock_propagate.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_back_updated_confidence_values(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """propagate_incremental result is written back for nodes with delta > 0.1."""
        node_id = str(uuid.uuid4())
        # Neighborhood has the target node with credibility 0.5
        mock_graph_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": node_id,
                    "credibility": 0.5,
                    "support_edge": None,
                    "contra_edge": None,
                }
            ]
        )
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None

        # Return a score that differs by > 0.1 to trigger the write-back
        new_confidence = 0.9
        mock_propagate = MagicMock(return_value={node_id: new_confidence})

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.epistemology.propagate_incremental", mock_propagate),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        mock_propagate.assert_called_once()
        call_kwargs = mock_propagate.call_args[1]
        assert call_kwargs["target_id"] == node_id
        assert node_id in call_kwargs["credibility_scores"]

        mock_graph_store.execute_write.assert_awaited_once()
        write_args = mock_graph_store.execute_write.call_args[0]
        write_params = write_args[1]
        assert write_params["node_id"] == node_id
        assert write_params["silo_id"] == "s1"
        assert write_params["confidence"] == new_confidence

    @pytest.mark.asyncio
    async def test_skips_write_when_confidence_unchanged(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """Nodes whose confidence changed by <= 0.1 are not written back."""
        node_id = str(uuid.uuid4())
        initial_credibility = 0.5
        mock_graph_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": node_id,
                    "credibility": initial_credibility,
                    "support_edge": None,
                    "contra_edge": None,
                }
            ]
        )
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None

        # Delta of 0.05 is below the 0.1 threshold
        mock_propagate = MagicMock(return_value={node_id: initial_credibility + 0.05})

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.epistemology.propagate_incremental", mock_propagate),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        mock_graph_store.execute_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_builds_edge_inputs_from_neighborhood_rows(
        self,
        in_memory_broker: InMemoryBroker,
        mock_context_service: MagicMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """Support and contradiction edges are extracted from query rows correctly."""
        node_id = str(uuid.uuid4())
        neighbor_id = str(uuid.uuid4())
        mock_graph_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": node_id,
                    "credibility": 0.7,
                    "support_edge": [node_id, neighbor_id, 0.8],
                    "contra_edge": None,
                },
                {
                    "node_id": neighbor_id,
                    "credibility": 0.6,
                    "support_edge": None,
                    "contra_edge": [neighbor_id, node_id, 0.5],
                },
            ]
        )
        task = in_memory_broker.find_task(ReactionEventType.PROPAGATE_CONFIDENCE)
        assert task is not None

        mock_propagate = MagicMock(return_value={})

        with (
            _patch_ctx_svc(mock_context_service),
            patch("context_service.sage.epistemology.propagate_incremental", mock_propagate),
        ):
            await task.kiq(node_id=node_id, silo_id="s1")

        mock_propagate.assert_called_once()
        call_kwargs = mock_propagate.call_args[1]
        assert (node_id, neighbor_id, 0.8) in call_kwargs["support_edges"]
        assert (neighbor_id, node_id, 0.5) in call_kwargs["contradiction_edges"]


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
            patch(
                "context_service.mcp.server.get_context_service", return_value=mock_context_service
            ),
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
            patch(
                "context_service.mcp.server.get_context_service", return_value=mock_context_service
            ),
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
