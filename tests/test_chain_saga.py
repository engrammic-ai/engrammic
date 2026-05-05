"""Tests for ChainSagaWriter: Postgres-first saga with Memgraph compensation."""

import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from context_service.engine.chain_saga import ChainSagaWriter
from context_service.models.inference import ChainStep


@pytest.fixture
def mock_postgres_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_memgraph_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def saga_writer(mock_postgres_store: AsyncMock, mock_memgraph_store: AsyncMock) -> ChainSagaWriter:
    return ChainSagaWriter(mock_postgres_store, mock_memgraph_store)


@pytest.mark.asyncio
async def test_saga_computes_summary_fields(
    saga_writer: ChainSagaWriter,
    mock_postgres_store: AsyncMock,
    mock_memgraph_store: AsyncMock,
) -> None:
    """Saga computes step_count, first_step, final_step from steps."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [
        ChainStep(step_index=0, operation="retrieve", conclusion="Found data", confidence=0.9),
        ChainStep(step_index=1, operation="synthesize", conclusion="Final answer", confidence=0.95),
    ]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    # Verify Postgres called first
    mock_postgres_store.upsert_chain_steps.assert_called_once()

    # Verify Memgraph called with summary fields
    mock_memgraph_store.upsert_reasoning_chain.assert_called_once()
    call_kwargs = mock_memgraph_store.upsert_reasoning_chain.call_args.kwargs
    assert call_kwargs["step_count"] == 2


@pytest.mark.asyncio
async def test_saga_passes_first_and_final_step(
    saga_writer: ChainSagaWriter,
    mock_memgraph_store: AsyncMock,
) -> None:
    """Saga includes first and final step in Memgraph summary."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [
        ChainStep(step_index=0, operation="retrieve", conclusion="Found data", confidence=0.9),
        ChainStep(step_index=1, operation="synthesize", conclusion="Final answer", confidence=0.95),
    ]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    call_kwargs = mock_memgraph_store.upsert_reasoning_chain.call_args.kwargs
    assert call_kwargs["first_step"] is not None
    assert "retrieve" in call_kwargs["first_step"]
    assert call_kwargs["final_step"] is not None
    assert "synthesize" in call_kwargs["final_step"]


@pytest.mark.asyncio
async def test_saga_compensates_on_memgraph_failure(
    saga_writer: ChainSagaWriter,
    mock_postgres_store: AsyncMock,
    mock_memgraph_store: AsyncMock,
) -> None:
    """On Memgraph failure, saga deletes Postgres row."""
    mock_memgraph_store.upsert_reasoning_chain.side_effect = Exception("Memgraph down")

    chain_id = uuid4()
    silo_id = uuid4()
    steps = [ChainStep(step_index=0, operation="test", conclusion="x", confidence=0.9)]

    with pytest.raises(Exception, match="Memgraph down"):
        await saga_writer.write_chain(
            chain_id=chain_id,
            silo_id=silo_id,
            steps=steps,
            produced_by_model="claude",
            produced_by_agent_id="agent-1",
        )

    mock_postgres_store.delete_chain_steps.assert_called_once_with(chain_id)


@pytest.mark.asyncio
async def test_saga_dead_letters_when_compensation_fails(
    saga_writer: ChainSagaWriter,
    mock_postgres_store: AsyncMock,
    mock_memgraph_store: AsyncMock,
) -> None:
    """When compensation delete also fails, chain is added to dead-letter table."""
    mock_memgraph_store.upsert_reasoning_chain.side_effect = Exception("Memgraph down")
    mock_postgres_store.delete_chain_steps.side_effect = Exception("Postgres also down")

    chain_id = uuid4()
    silo_id = uuid4()
    steps = [ChainStep(step_index=0, operation="test", conclusion="x", confidence=0.9)]

    with pytest.raises(Exception, match="Memgraph down"):
        await saga_writer.write_chain(
            chain_id=chain_id,
            silo_id=silo_id,
            steps=steps,
            produced_by_model="claude",
            produced_by_agent_id="agent-1",
        )

    mock_postgres_store.add_orphaned_chain.assert_called_once_with(
        chain_id, silo_id, "Memgraph down"
    )


@pytest.mark.asyncio
async def test_saga_derives_outcome_success(
    saga_writer: ChainSagaWriter,
    mock_memgraph_store: AsyncMock,
) -> None:
    """High-confidence final step yields 'success' outcome."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [ChainStep(step_index=0, operation="test", conclusion="done", confidence=0.9)]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    call_kwargs = mock_memgraph_store.upsert_reasoning_chain.call_args.kwargs
    assert call_kwargs["outcome"] == "success"


@pytest.mark.asyncio
async def test_saga_derives_outcome_failure(
    saga_writer: ChainSagaWriter,
    mock_memgraph_store: AsyncMock,
) -> None:
    """Low-confidence final step yields 'failure' outcome."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [ChainStep(step_index=0, operation="test", conclusion="done", confidence=0.3)]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    call_kwargs = mock_memgraph_store.upsert_reasoning_chain.call_args.kwargs
    assert call_kwargs["outcome"] == "failure"


@pytest.mark.asyncio
async def test_saga_collects_all_premise_refs(
    saga_writer: ChainSagaWriter,
    mock_memgraph_store: AsyncMock,
) -> None:
    """Saga collects premise_refs from all steps."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [
        ChainStep(
            step_index=0,
            operation="retrieve",
            conclusion="A",
            confidence=0.9,
            premise_refs=["ref-1", "ref-2"],
        ),
        ChainStep(
            step_index=1,
            operation="synthesize",
            conclusion="B",
            confidence=0.95,
            premise_refs=["ref-3"],
        ),
    ]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    call_kwargs = mock_memgraph_store.upsert_reasoning_chain.call_args.kwargs
    assert set(call_kwargs["all_premise_refs"]) == {"ref-1", "ref-2", "ref-3"}
