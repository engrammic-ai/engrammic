"""Tests for UsageService record and aggregation operations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from context_service.models.postgres.usage import ToolUsageSummary
from context_service.services.usage import UsageService

USER_ID = uuid4()
SILO_ID = "silo_test"
TOOL_NAME = "remember"


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


@pytest.fixture
def service(session: AsyncMock) -> UsageService:
    return UsageService(session)


def _make_summary_row(tool_name: str, count: int, last_used: datetime) -> MagicMock:
    row = MagicMock()
    row.tool_name = tool_name
    row.count = count
    row.last_used = last_used
    return row


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_adds_and_flushes(service: UsageService, session: AsyncMock) -> None:
    await service.record_usage(user_id=USER_ID, silo_id=SILO_ID, tool_name=TOOL_NAME)

    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_usage_creates_tool_usage_row(
    service: UsageService, session: AsyncMock
) -> None:
    with patch("context_service.services.usage.ToolUsage") as MockToolUsage:
        mock_row = MagicMock()
        MockToolUsage.return_value = mock_row

        await service.record_usage(user_id=USER_ID, silo_id=SILO_ID, tool_name=TOOL_NAME)

        MockToolUsage.assert_called_once_with(user_id=USER_ID, silo_id=SILO_ID, tool_name=TOOL_NAME)
        session.add.assert_called_once_with(mock_row)


# ---------------------------------------------------------------------------
# get_user_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_usage_returns_summaries(service: UsageService, session: AsyncMock) -> None:
    now = datetime.now(UTC)
    row1 = _make_summary_row("remember", 5, now)
    row2 = _make_summary_row("learn", 2, now)

    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    session.execute.return_value = mock_result

    summaries = await service.get_user_usage(user_id=USER_ID)

    assert len(summaries) == 2
    assert summaries[0].tool_name == "remember"
    assert summaries[0].count == 5
    assert summaries[0].last_used == now
    assert summaries[1].tool_name == "learn"
    assert summaries[1].count == 2


@pytest.mark.asyncio
async def test_get_user_usage_empty_result(service: UsageService, session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result

    summaries = await service.get_user_usage(user_id=USER_ID)

    assert summaries == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_usage_with_since_calls_execute(
    service: UsageService, session: AsyncMock
) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result

    await service.get_user_usage(user_id=USER_ID, since=since)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_usage_returns_tool_usage_summary_instances(
    service: UsageService, session: AsyncMock
) -> None:
    now = datetime.now(UTC)
    row = _make_summary_row("recall", 3, now)
    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    session.execute.return_value = mock_result

    summaries = await service.get_user_usage(user_id=USER_ID)

    assert len(summaries) == 1
    assert isinstance(summaries[0], ToolUsageSummary)


# ---------------------------------------------------------------------------
# get_silo_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_silo_usage_returns_summaries(service: UsageService, session: AsyncMock) -> None:
    now = datetime.now(UTC)
    row1 = _make_summary_row("believe", 10, now)
    row2 = _make_summary_row("trace", 1, now)

    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    session.execute.return_value = mock_result

    summaries = await service.get_silo_usage(silo_id=SILO_ID)

    assert len(summaries) == 2
    assert summaries[0].tool_name == "believe"
    assert summaries[0].count == 10
    assert summaries[1].tool_name == "trace"
    assert summaries[1].count == 1


@pytest.mark.asyncio
async def test_get_silo_usage_empty_result(service: UsageService, session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result

    summaries = await service.get_silo_usage(silo_id=SILO_ID)

    assert summaries == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_silo_usage_with_since_calls_execute(
    service: UsageService, session: AsyncMock
) -> None:
    since = datetime(2026, 3, 1, tzinfo=UTC)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result

    await service.get_silo_usage(silo_id=SILO_ID, since=since)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_silo_usage_returns_tool_usage_summary_instances(
    service: UsageService, session: AsyncMock
) -> None:
    now = datetime.now(UTC)
    row = _make_summary_row("link", 7, now)
    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    session.execute.return_value = mock_result

    summaries = await service.get_silo_usage(silo_id=SILO_ID)

    assert len(summaries) == 1
    assert isinstance(summaries[0], ToolUsageSummary)
