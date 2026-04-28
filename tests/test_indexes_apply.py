"""Regression test for R-001 — apply_all_indexes runs every DDL statement and
swallows per-statement failures so startup is not blocked by an index that
already exists. See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from context_service.db.indexes import ALL_INDEX_QUERIES, apply_all_indexes


class _FakeSession:
    def __init__(self, calls: list[str], fail_on: set[str]) -> None:
        self._calls = calls
        self._fail_on = fail_on

    async def run(self, statement: str) -> Any:
        self._calls.append(statement)
        if statement in self._fail_on:
            raise RuntimeError(f"simulated index failure on {statement!r}")
        result = MagicMock()
        result.consume = AsyncMock(return_value=None)
        return result


class _FakeClient:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._fail_on = fail_on or set()

    @asynccontextmanager
    async def session(self) -> Any:
        yield _FakeSession(self.calls, self._fail_on)


async def test_apply_all_indexes_runs_every_statement() -> None:
    client = _FakeClient()
    await apply_all_indexes(client)  # type: ignore[arg-type]
    assert client.calls == list(ALL_INDEX_QUERIES)


async def test_apply_all_indexes_continues_after_per_statement_failure() -> None:
    failing = ALL_INDEX_QUERIES[3]
    client = _FakeClient(fail_on={failing})
    await apply_all_indexes(client)  # type: ignore[arg-type]
    assert failing in client.calls
    assert len(client.calls) == len(ALL_INDEX_QUERIES)
