"""Tests for TX1 EXTRACT handler (extract_claims_task)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reactions.events import ReactionEventType


@pytest.fixture
def mock_node() -> MagicMock:
    """Create a mock Memory node."""
    node = MagicMock()
    node.id = uuid.uuid4()
    node.type = "Observation"
    node.content = "The API endpoint /users returns a 500 error when the database connection times out. This happens because the connection pool is exhausted under high load."
    node.properties = {}
    return node


@pytest.fixture
def mock_short_node() -> MagicMock:
    """Create a mock Memory node with short content."""
    node = MagicMock()
    node.id = uuid.uuid4()
    node.type = "Observation"
    node.content = "Short content"
    node.properties = {}
    return node


@pytest.fixture
def mock_already_extracted_node() -> MagicMock:
    """Create a mock Memory node that was already extracted."""
    node = MagicMock()
    node.id = uuid.uuid4()
    node.type = "Observation"
    node.content = "Long content " * 50
    node.properties = {"extracted_at": "2026-06-01T00:00:00Z", "extraction_version": "v1"}
    return node


@pytest.fixture
def mock_context_service() -> MagicMock:
    """Create a mock context service."""
    ctx = MagicMock()
    ctx.graph_store = AsyncMock()
    ctx.vector_store = AsyncMock()
    return ctx


@pytest.fixture
def mock_llm_response() -> str:
    """Mock LLM extraction response."""
    return '[{"content": "The /users endpoint returns 500 on database timeout", "raw_confidence": 0.9}, {"content": "Connection pool exhaustion causes timeouts under high load", "raw_confidence": 0.85}]'


class TestExtractClaimsTask:
    """Tests for extract_claims_task handler."""

    @pytest.mark.asyncio
    async def test_extract_skips_short_content(
        self, mock_short_node: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Content below threshold should skip LLM extraction."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_short_node)

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.reactions.tasks.build_llm_provider") as mock_llm,
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            assert handler is not None

            await handler(
                node_id=str(mock_short_node.id),
                silo_id="test-silo",
            )

            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_creates_claims(
        self,
        mock_node: MagicMock,
        mock_context_service: MagicMock,
        mock_llm_response: str,
    ) -> None:
        """LLM extraction should create claims via store_claim."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_node)
        mock_context_service.graph_store.execute_write = AsyncMock(return_value=[])
        mock_context_service.vector_store.search = AsyncMock(return_value=[])

        mock_embedder = AsyncMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=mock_llm_response)

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.reactions.tasks.build_llm_provider",
                return_value=mock_llm,
            ),
            patch(
                "context_service.reactions.tasks.build_embedding_service",
                return_value=mock_embedder,
            ),
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
            patch("context_service.reactions.tasks.store_claim") as mock_store_claim,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            claim_result = MagicMock()
            claim_result.claim_id = uuid.uuid4()
            mock_store_claim.return_value = claim_result

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(node_id=str(mock_node.id), silo_id="test-silo")

            assert mock_store_claim.call_count == 2

    @pytest.mark.asyncio
    async def test_extract_idempotent(
        self, mock_already_extracted_node: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Already extracted nodes should be skipped."""
        mock_context_service.graph_store.get_node = AsyncMock(
            return_value=mock_already_extracted_node
        )

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.reactions.tasks.build_llm_provider") as mock_llm,
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(
                node_id=str(mock_already_extracted_node.id),
                silo_id="test-silo",
            )

            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(
        self, mock_node: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """LLM errors should be handled gracefully."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_node)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.reactions.tasks.build_llm_provider",
                return_value=mock_llm,
            ),
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
            patch("context_service.reactions.tasks.store_claim") as mock_store_claim,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(node_id=str(mock_node.id), silo_id="test-silo")

            mock_store_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_dedup_creates_corroborates(
        self, mock_node: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Similar existing claim should create CORROBORATES edge instead of duplicate."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_node)
        mock_context_service.graph_store.execute_write = AsyncMock(return_value=[])
        mock_context_service.graph_store.upsert_binary_edge = AsyncMock()

        existing_claim_id = str(uuid.uuid4())
        mock_context_service.vector_store.search = AsyncMock(
            return_value=[{"node_id": existing_claim_id}]
        )

        mock_embedder = AsyncMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='[{"content": "Test claim", "raw_confidence": 0.9}]'
        )

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.reactions.tasks.build_llm_provider",
                return_value=mock_llm,
            ),
            patch(
                "context_service.reactions.tasks.build_embedding_service",
                return_value=mock_embedder,
            ),
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
            patch("context_service.reactions.tasks.store_claim") as mock_store_claim,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(node_id=str(mock_node.id), silo_id="test-silo")

            mock_store_claim.assert_not_called()
            mock_context_service.graph_store.upsert_binary_edge.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_credibility_scaled(
        self,
        mock_node: MagicMock,
        mock_context_service: MagicMock,
    ) -> None:
        """Credibility should be scaled per CITE v2: 0.6 * 0.75 * raw_confidence."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_node)
        mock_context_service.graph_store.execute_write = AsyncMock(return_value=[])
        mock_context_service.vector_store.search = AsyncMock(return_value=[])

        mock_embedder = AsyncMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='[{"content": "Test claim", "raw_confidence": 0.9}]'
        )

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.reactions.tasks.build_llm_provider",
                return_value=mock_llm,
            ),
            patch(
                "context_service.reactions.tasks.build_embedding_service",
                return_value=mock_embedder,
            ),
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
            patch("context_service.reactions.tasks.store_claim") as mock_store_claim,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            claim_result = MagicMock()
            claim_result.claim_id = uuid.uuid4()
            mock_store_claim.return_value = claim_result

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(node_id=str(mock_node.id), silo_id="test-silo")

            call_kwargs = mock_store_claim.call_args.kwargs
            assert call_kwargs["confidence"] == 0.9
            assert call_kwargs["source_tier"] == "community"

    @pytest.mark.asyncio
    async def test_extract_links_to_source(
        self,
        mock_node: MagicMock,
        mock_context_service: MagicMock,
    ) -> None:
        """Extracted claims should have EXTRACTED_FROM edge to source Memory."""
        mock_context_service.graph_store.get_node = AsyncMock(return_value=mock_node)
        mock_context_service.graph_store.execute_write = AsyncMock(return_value=[])
        mock_context_service.graph_store.upsert_binary_edge = AsyncMock()
        mock_context_service.vector_store.search = AsyncMock(return_value=[])

        mock_embedder = AsyncMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='[{"content": "Test claim", "raw_confidence": 0.9}]'
        )

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.reactions.tasks.build_llm_provider",
                return_value=mock_llm,
            ),
            patch(
                "context_service.reactions.tasks.build_embedding_service",
                return_value=mock_embedder,
            ),
            patch("context_service.reactions.tasks.layer_for_label") as mock_layer,
            patch("context_service.reactions.tasks.store_claim") as mock_store_claim,
        ):
            from primitives.schema.labels import PersistenceLayer

            mock_layer.return_value = PersistenceLayer.MEMORY

            claim_result = MagicMock()
            claim_result.claim_id = uuid.uuid4()
            mock_store_claim.return_value = claim_result

            from context_service.reactions.tasks import register_tasks
            from taskiq_redis import ListQueueBroker

            broker = MagicMock(spec=ListQueueBroker)
            registered_tasks: dict[str, Any] = {}

            def capture_task(task_name: str, **kwargs: Any):
                def decorator(fn: Any) -> Any:
                    registered_tasks[task_name] = fn
                    return fn

                return decorator

            broker.task = capture_task
            register_tasks(broker)

            handler = registered_tasks.get(ReactionEventType.CHECK_EXTRACTION_TRIGGER)
            await handler(node_id=str(mock_node.id), silo_id="test-silo")

            edge_call = mock_context_service.graph_store.upsert_binary_edge.call_args
            edge = edge_call.args[0]
            from primitives.schema.edges import CITEEdgeType

            assert edge.edge_type == CITEEdgeType.EXTRACTED_FROM
            assert edge.target_id == mock_node.id
