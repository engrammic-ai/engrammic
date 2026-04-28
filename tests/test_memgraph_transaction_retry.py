"""Regression test for N-012 — run_in_transaction retries transient errors.
See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j.exceptions import ClientError, ServiceUnavailable

from context_service.stores.memgraph import MemgraphClient


def _make_client_with_mock_session() -> tuple[MemgraphClient, MagicMock]:
    driver = MagicMock()
    session_mock = MagicMock()
    tx_mock = MagicMock()
    tx_mock.commit = AsyncMock()
    tx_mock.rollback = AsyncMock()
    session_mock.begin_transaction = AsyncMock(return_value=tx_mock)
    session_mock.close = AsyncMock()
    driver.session = MagicMock(return_value=session_mock)
    return MemgraphClient(driver), session_mock


async def test_run_in_transaction_retries_on_service_unavailable() -> None:
    client, _ = _make_client_with_mock_session()
    attempts: list[int] = []

    async def body(_tx: Any) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise ServiceUnavailable("simulated")
        return "ok"

    result = await client.run_in_transaction(body)
    assert result == "ok"
    assert len(attempts) == 2


async def test_run_in_transaction_retries_on_transient_client_error() -> None:
    client, _ = _make_client_with_mock_session()
    attempts: list[int] = []

    class _Deadlock(ClientError):
        code = "Memgraph.TransientError.DeadlockDetected"

    deadlock = _Deadlock("deadlock")

    async def body(_tx: Any) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise deadlock
        return "ok"

    result = await client.run_in_transaction(body)
    assert result == "ok"
    assert len(attempts) == 3


async def test_run_in_transaction_does_not_retry_logical_errors() -> None:
    client, _ = _make_client_with_mock_session()
    attempts: list[int] = []

    class _Constraint(ClientError):
        code = "Neo.ClientError.Schema.ConstraintValidationFailed"

    constraint = _Constraint("constraint violation")

    async def body(_tx: Any) -> Any:
        attempts.append(1)
        raise constraint

    with pytest.raises(ClientError):
        await client.run_in_transaction(body)
    assert len(attempts) == 1
