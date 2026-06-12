"""Tests for TX6 CONSENSUS handler (check_consensus_task)."""

from __future__ import annotations

import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub heavy imports before importing task module
_STUBS = {
    "context_service.mcp.server": MagicMock(),
    "context_service.db.postgres": MagicMock(),
}
for name, stub in _STUBS.items():
    if name not in sys.modules:
        sys.modules[name] = stub


@pytest.fixture
def mock_chain() -> MagicMock:
    """Mock ReasoningChainSteps row."""
    chain = MagicMock()
    chain.chain_id = uuid.uuid4()
    chain.silo_id = uuid.uuid4()
    chain.agent_id = "agent-1"
    chain.conclusion = "The API timeout is caused by connection pool exhaustion"
    chain.conclusion_embedding = [0.1] * 768
    chain.steps_json = [{"step": "observed 500 errors", "order": 1}]
    return chain


@pytest.fixture
def mock_similar_chain() -> MagicMock:
    """Mock similar chain for consensus."""
    chain = MagicMock()
    chain.chain_id = uuid.uuid4()
    chain.silo_id = uuid.uuid4()
    chain.agent_id = "agent-2"
    chain.conclusion = "Connection pool exhaustion causes API timeouts"
    chain.conclusion_embedding = [0.11] * 768
    chain.steps_json = [{"step": "checked pool metrics", "order": 1}]
    return chain


@pytest.fixture
def mock_context_service() -> MagicMock:
    """Mock context service."""
    ctx = MagicMock()
    ctx.graph_store = AsyncMock()
    ctx.graph_store.execute_query = AsyncMock(return_value=[])
    ctx.graph_store.execute_write = AsyncMock(return_value=[{"id": str(uuid.uuid4())}])
    ctx.graph_store.upsert_binary_edge = AsyncMock()
    ctx.vector_store = AsyncMock()
    return ctx


def _capture_broker_tasks(broker: MagicMock) -> dict[str, Any]:
    """Helper to capture registered tasks from broker."""
    registered: dict[str, Any] = {}

    def capture_task(task_name: str, **_kwargs: Any):
        def decorator(fn: Any) -> Any:
            registered[task_name] = fn
            return fn

        return decorator

    broker.task = capture_task
    return registered


class TestCheckConsensusThresholds:
    """Tests for consensus threshold logic."""

    @pytest.mark.asyncio
    async def test_insufficient_chains_skips(
        self, mock_chain: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Consensus requires K chains (default 3)."""
        from context_service.reactions.events import ReactionEventType

        mock_pg_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_chain
        mock_pg_session.__aenter__.return_value.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.db.postgres.get_session", return_value=mock_pg_session),
            patch(
                "context_service.reactions.tasks.search_chains", new_callable=AsyncMock
            ) as mock_search,
        ):
            # Only one similar chain found (below K=3 threshold)
            mock_search.return_value = []

            from context_service.reactions.tasks import register_tasks

            broker = MagicMock()
            tasks = _capture_broker_tasks(broker)
            register_tasks(broker)

            handler = tasks.get(ReactionEventType.CHECK_CONSENSUS)
            assert handler is not None

            await handler(
                node_id=str(mock_chain.chain_id),
                silo_id=str(mock_chain.silo_id),
            )

            # Should not create Fact
            mock_context_service.graph_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_insufficient_agents_skips(
        self, mock_chain: MagicMock, mock_similar_chain: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Consensus requires J distinct agents (default 2)."""
        from context_service.reactions.events import ReactionEventType

        # Make similar chain from same agent
        mock_similar_chain.agent_id = mock_chain.agent_id

        mock_pg_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_chain
        mock_result.scalars.return_value.all.return_value = [mock_similar_chain]
        mock_pg_session.__aenter__.return_value.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.db.postgres.get_session", return_value=mock_pg_session),
            patch(
                "context_service.reactions.tasks.search_chains", new_callable=AsyncMock
            ) as mock_search,
            patch(
                "context_service.reactions.tasks._chains_reasoning_compatible", return_value=True
            ),
        ):
            mock_search.return_value = [{"id": str(mock_similar_chain.chain_id)}]

            from context_service.reactions.tasks import register_tasks

            broker = MagicMock()
            tasks = _capture_broker_tasks(broker)
            register_tasks(broker)

            handler = tasks.get(ReactionEventType.CHECK_CONSENSUS)
            await handler(
                node_id=str(mock_chain.chain_id),
                silo_id=str(mock_chain.silo_id),
            )

            # Should not create Fact (same agent for all chains)
            mock_context_service.graph_store.execute_write.assert_not_called()


class TestCheckConsensusCreatesFact:
    """Tests for Fact creation on successful consensus."""

    @pytest.mark.asyncio
    async def test_creates_fact_on_consensus(
        self, mock_chain: MagicMock, mock_similar_chain: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """K chains from J agents creates Fact."""
        from context_service.reactions.events import ReactionEventType

        # Need 3 chains from 2 agents minimum
        chain3 = MagicMock()
        chain3.chain_id = uuid.uuid4()
        chain3.agent_id = "agent-3"
        chain3.conclusion_embedding = [0.12] * 768
        chain3.steps_json = []

        mock_pg_session = AsyncMock()
        mock_result_first = MagicMock()
        mock_result_first.scalar_one_or_none.return_value = mock_chain
        mock_result_candidates = MagicMock()
        mock_result_candidates.scalars.return_value.all.return_value = [mock_similar_chain, chain3]

        call_count = 0

        async def mock_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result_first
            return mock_result_candidates

        mock_pg_session.__aenter__.return_value.execute = mock_execute

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.db.postgres.get_session", return_value=mock_pg_session),
            patch(
                "context_service.reactions.tasks.search_chains", new_callable=AsyncMock
            ) as mock_search,
            patch(
                "context_service.reactions.tasks._chains_reasoning_compatible", return_value=True
            ),
            patch(
                "context_service.reactions.tasks._find_existing_consensus_fact",
                new_callable=AsyncMock,
            ) as mock_find,
            patch("context_service.reactions.tasks.emit_reaction", new_callable=AsyncMock),
        ):
            mock_search.return_value = [
                {"id": str(mock_similar_chain.chain_id)},
                {"id": str(chain3.chain_id)},
            ]
            mock_find.return_value = None  # No existing fact

            from context_service.reactions.tasks import register_tasks

            broker = MagicMock()
            tasks = _capture_broker_tasks(broker)
            register_tasks(broker)

            handler = tasks.get(ReactionEventType.CHECK_CONSENSUS)
            await handler(
                node_id=str(mock_chain.chain_id),
                silo_id=str(mock_chain.silo_id),
            )

            # Should create Fact via execute_write
            assert mock_context_service.graph_store.execute_write.called


class TestCheckConsensusExtends:
    """Tests for extending existing consensus."""

    @pytest.mark.asyncio
    async def test_extends_existing_consensus(
        self, mock_chain: MagicMock, mock_similar_chain: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Existing consensus Fact gets edges to new chain."""
        from context_service.reactions.events import ReactionEventType

        existing_fact_id = str(uuid.uuid4())
        chain3 = MagicMock()
        chain3.chain_id = uuid.uuid4()
        chain3.agent_id = "agent-3"
        chain3.conclusion_embedding = [0.12] * 768
        chain3.steps_json = []

        mock_pg_session = AsyncMock()
        mock_result_first = MagicMock()
        mock_result_first.scalar_one_or_none.return_value = mock_chain
        mock_result_candidates = MagicMock()
        mock_result_candidates.scalars.return_value.all.return_value = [mock_similar_chain, chain3]

        call_count = 0

        async def mock_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result_first
            return mock_result_candidates

        mock_pg_session.__aenter__.return_value.execute = mock_execute

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.db.postgres.get_session", return_value=mock_pg_session),
            patch(
                "context_service.reactions.tasks.search_chains", new_callable=AsyncMock
            ) as mock_search,
            patch(
                "context_service.reactions.tasks._chains_reasoning_compatible", return_value=True
            ),
            patch(
                "context_service.reactions.tasks._find_existing_consensus_fact",
                new_callable=AsyncMock,
            ) as mock_find,
        ):
            mock_search.return_value = [
                {"id": str(mock_similar_chain.chain_id)},
                {"id": str(chain3.chain_id)},
            ]
            mock_find.return_value = existing_fact_id  # Existing fact

            from context_service.reactions.tasks import register_tasks

            broker = MagicMock()
            tasks = _capture_broker_tasks(broker)
            register_tasks(broker)

            handler = tasks.get(ReactionEventType.CHECK_CONSENSUS)
            await handler(
                node_id=str(mock_chain.chain_id),
                silo_id=str(mock_chain.silo_id),
            )

            # Should add edges, not create new Fact
            assert mock_context_service.graph_store.upsert_binary_edge.called
            mock_context_service.graph_store.execute_write.assert_not_called()


class TestCheckConsensusDTW:
    """Tests for DTW reasoning compatibility filtering."""

    @pytest.mark.asyncio
    async def test_incompatible_reasoning_filtered(
        self, mock_chain: MagicMock, mock_similar_chain: MagicMock, mock_context_service: MagicMock
    ) -> None:
        """Chains with different reasoning paths are filtered out."""
        from context_service.reactions.events import ReactionEventType

        mock_pg_session = AsyncMock()
        mock_result_first = MagicMock()
        mock_result_first.scalar_one_or_none.return_value = mock_chain
        mock_result_candidates = MagicMock()
        mock_result_candidates.scalars.return_value.all.return_value = [mock_similar_chain]

        call_count = 0

        async def mock_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result_first
            return mock_result_candidates

        mock_pg_session.__aenter__.return_value.execute = mock_execute

        with (
            patch(
                "context_service.reactions.tasks.get_context_service",
                return_value=mock_context_service,
            ),
            patch("context_service.db.postgres.get_session", return_value=mock_pg_session),
            patch(
                "context_service.reactions.tasks.search_chains", new_callable=AsyncMock
            ) as mock_search,
            patch(
                "context_service.reactions.tasks._chains_reasoning_compatible", return_value=False
            ),
        ):
            mock_search.return_value = [{"id": str(mock_similar_chain.chain_id)}]

            from context_service.reactions.tasks import register_tasks

            broker = MagicMock()
            tasks = _capture_broker_tasks(broker)
            register_tasks(broker)

            handler = tasks.get(ReactionEventType.CHECK_CONSENSUS)
            await handler(
                node_id=str(mock_chain.chain_id),
                silo_id=str(mock_chain.silo_id),
            )

            # Should not create Fact (DTW filtered candidate)
            mock_context_service.graph_store.execute_write.assert_not_called()
