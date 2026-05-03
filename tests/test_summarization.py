from unittest.mock import AsyncMock

import pytest

from context_service.engine.summarization import (
    inline_summary,
    summarize_reasoning_steps,
)


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(return_value=("Summary of reasoning chain.", None))
    return client


def test_inline_summary_formats_steps() -> None:
    steps = [
        {"step_index": 0, "operation": "analyze", "conclusion": "First"},
        {"step_index": 1, "operation": "decide", "conclusion": "Second"},
    ]
    result = inline_summary(steps)
    assert "[0] analyze: First" in result
    assert "[1] decide: Second" in result


def test_inline_summary_empty() -> None:
    assert inline_summary([]) == "(no steps)"


@pytest.mark.asyncio
async def test_summarize_short_chain_returns_inline() -> None:
    steps = [{"step_index": 0, "operation": "analyze", "conclusion": "Only one"}]
    result = await summarize_reasoning_steps(steps, llm_client=None)
    assert "Only one" in result


@pytest.mark.asyncio
async def test_summarize_long_chain_calls_llm(mock_llm_client: AsyncMock) -> None:
    steps = [
        {"step_index": i, "operation": "analyze", "conclusion": f"Step {i}"} for i in range(10)
    ]
    result = await summarize_reasoning_steps(steps, llm_client=mock_llm_client)
    assert result == "Summary of reasoning chain."
    mock_llm_client.complete.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_long_chain_no_client_raises() -> None:
    steps = [{"step_index": i, "operation": "x", "conclusion": "y"} for i in range(10)]
    with pytest.raises(ValueError, match="LLM client required"):
        await summarize_reasoning_steps(steps, llm_client=None)
