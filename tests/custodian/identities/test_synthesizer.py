from unittest.mock import AsyncMock, patch

import pytest

from context_service.custodian.identities.synthesizer import (
    SynthesisResult,
    SynthesizerIdentity,
)


@pytest.mark.asyncio
async def test_synthesizer_finds_candidates():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"cluster_id": "c1", "fact_count": 5, "confidence": 0.8},
    ]

    synthesizer = SynthesizerIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-pro",
    )

    candidates = await synthesizer.find_synthesis_candidates()
    assert len(candidates) == 1
    assert candidates[0]["cluster_id"] == "c1"


@pytest.mark.asyncio
async def test_synthesizer_no_candidates_returns_zero():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []

    synthesizer = SynthesizerIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="test-model",
    )

    result = await synthesizer.run_synthesis()
    assert result["candidates"] == 0
    assert result["created"] == 0


@pytest.mark.asyncio
async def test_synthesizer_creates_proposed_belief():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"cluster_id": "c1", "fact_count": 5, "confidence": 0.8}],
        [
            {"id": "f1", "content": "Fact one"},
            {"id": "f2", "content": "Fact two"},
            {"id": "f3", "content": "Fact three"},
        ],
    ]
    mock_store.execute_write.return_value = None

    mock_result = AsyncMock()
    mock_result.output = SynthesisResult(
        belief_statement="Synthesized belief from facts",
        confidence=0.85,
        supporting_fact_ids=["f1", "f2"],
        reasoning="Facts agree on topic",
    )

    with patch(
        "context_service.custodian.identities.synthesizer._build_synthesis_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        synthesizer = SynthesizerIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
        )

        result = await synthesizer.run_synthesis()

    assert result["candidates"] == 1
    assert result["created"] == 1
    mock_store.execute_write.assert_called_once()


@pytest.mark.asyncio
async def test_synthesizer_low_confidence_skips_creation():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"cluster_id": "c1", "fact_count": 5, "confidence": 0.8}],
        [
            {"id": "f1", "content": "Fact one"},
            {"id": "f2", "content": "Fact two"},
            {"id": "f3", "content": "Fact three"},
        ],
    ]

    mock_result = AsyncMock()
    mock_result.output = SynthesisResult(
        belief_statement="Weak belief",
        confidence=0.3,
        supporting_fact_ids=["f1"],
        reasoning="Facts barely agree",
    )

    with patch(
        "context_service.custodian.identities.synthesizer._build_synthesis_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        synthesizer = SynthesizerIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
            proposal_threshold=0.6,
        )

        result = await synthesizer.run_synthesis()

    assert result["candidates"] == 1
    assert result["created"] == 0
    mock_store.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_synthesizer_filters_invalid_fact_ids():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"cluster_id": "c1", "fact_count": 3, "confidence": 0.8}],
        [
            {"id": "f1", "content": "Fact one"},
            {"id": "f2", "content": "Fact two"},
            {"id": "f3", "content": "Fact three"},
        ],
    ]
    mock_store.execute_write.return_value = None

    mock_result = AsyncMock()
    mock_result.output = SynthesisResult(
        belief_statement="Belief statement",
        confidence=0.9,
        supporting_fact_ids=["f1", "hallucinated-id"],
        reasoning="Facts support belief",
    )

    with patch(
        "context_service.custodian.identities.synthesizer._build_synthesis_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        synthesizer = SynthesizerIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
        )

        result = await synthesizer.run_synthesis()

    assert result["created"] == 1
    call_args = mock_store.execute_write.call_args
    assert "hallucinated-id" not in call_args[0][1]["fact_ids"]


@pytest.mark.asyncio
async def test_synthesizer_timeout_continues_to_next():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [
            {"cluster_id": "c1", "fact_count": 3, "confidence": 0.8},
            {"cluster_id": "c2", "fact_count": 4, "confidence": 0.9},
        ],
        [
            {"id": "f1", "content": "Fact"},
            {"id": "f2", "content": "Fact"},
            {"id": "f3", "content": "Fact"},
        ],
        [
            {"id": "f4", "content": "Fact"},
            {"id": "f5", "content": "Fact"},
            {"id": "f6", "content": "Fact"},
        ],
    ]
    mock_store.execute_write.return_value = None

    mock_result = AsyncMock()
    mock_result.output = SynthesisResult(
        belief_statement="Belief",
        confidence=0.9,
        supporting_fact_ids=["f4", "f5"],
        reasoning="OK",
    )

    with patch(
        "context_service.custodian.identities.synthesizer._build_synthesis_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.side_effect = [TimeoutError(), mock_result]
        mock_agent.return_value = agent_instance

        synthesizer = SynthesizerIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
        )

        result = await synthesizer.run_synthesis()

    assert result["candidates"] == 2
    assert result["created"] == 1
