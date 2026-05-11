from unittest.mock import AsyncMock, patch

import pytest

from context_service.custodian.identities.custodian import (
    ContradictionAnalysis,
    CustodianIdentity,
)


@pytest.mark.asyncio
async def test_custodian_no_similar_facts_returns_no_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []

    custodian = CustodianIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-flash",
    )

    result = await custodian.check_contradiction("new-fact-id")
    assert result.has_contradiction is False
    assert result.supersedes_ids == []


@pytest.mark.asyncio
async def test_custodian_llm_detects_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"fact_id": "old-fact", "content": "X is true"}],
        [{"content": "X is false"}],
    ]

    mock_result = AsyncMock()
    mock_result.output = ContradictionAnalysis(
        has_contradiction=True,
        supersedes=["old-fact"],
        reasoning="Direct negation",
        confidence=0.9,
    )

    with patch(
        "context_service.custodian.identities.custodian._build_contradiction_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        custodian = CustodianIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
        )

        result = await custodian.check_contradiction("new-fact")

    assert result.has_contradiction is True
    assert "old-fact" in result.supersedes_ids
    assert result.reason == "Direct negation"


@pytest.mark.asyncio
async def test_custodian_low_confidence_returns_no_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"fact_id": "old-fact", "content": "X is true"}],
        [{"content": "X might be false"}],
    ]

    mock_result = AsyncMock()
    mock_result.output = ContradictionAnalysis(
        has_contradiction=True,
        supersedes=["old-fact"],
        reasoning="Uncertain",
        confidence=0.3,
    )

    with patch(
        "context_service.custodian.identities.custodian._build_contradiction_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        custodian = CustodianIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
            min_confidence=0.7,
        )

        result = await custodian.check_contradiction("new-fact")

    assert result.has_contradiction is False


@pytest.mark.asyncio
async def test_custodian_filters_invalid_fact_ids():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"fact_id": "real-fact", "content": "X is true"}],
        [{"content": "X is false"}],
    ]

    mock_result = AsyncMock()
    mock_result.output = ContradictionAnalysis(
        has_contradiction=True,
        supersedes=["real-fact", "hallucinated-fact"],
        reasoning="Contradiction detected",
        confidence=0.9,
    )

    with patch(
        "context_service.custodian.identities.custodian._build_contradiction_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.return_value = mock_result
        mock_agent.return_value = agent_instance

        custodian = CustodianIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
        )

        result = await custodian.check_contradiction("new-fact")

    assert result.has_contradiction is True
    assert result.supersedes_ids == ["real-fact"]
    assert "hallucinated-fact" not in result.supersedes_ids


@pytest.mark.asyncio
async def test_custodian_timeout_returns_no_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"fact_id": "old-fact", "content": "X is true"}],
        [{"content": "X is false"}],
    ]

    with patch(
        "context_service.custodian.identities.custodian._build_contradiction_agent"
    ) as mock_agent:
        agent_instance = AsyncMock()
        agent_instance.run.side_effect = TimeoutError()
        mock_agent.return_value = agent_instance

        custodian = CustodianIdentity(
            store=mock_store,
            silo_id="test-silo",
            model="test-model",
            timeout_seconds=0.1,
        )

        result = await custodian.check_contradiction("new-fact")

    assert result.has_contradiction is False
