# tests/pipelines/test_orphan_recovery.py
"""Tests for orphan chain recovery job."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestBackoffElapsed:
    """Tests for backoff timing logic."""

    def test_first_retry_always_eligible(self):
        """First retry (last_retry_at=None) should always be eligible."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed

        assert backoff_elapsed(retry_count=0, last_retry_at=None) is True

    def test_backoff_not_elapsed(self):
        """Should return False when backoff period not elapsed."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed

        # retry_count=1 means wait 10 minutes (2^1 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=5)
        assert backoff_elapsed(retry_count=1, last_retry_at=last_retry) is False

    def test_backoff_elapsed(self):
        """Should return True when backoff period has elapsed."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed

        # retry_count=1 means wait 10 minutes (2^1 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=15)
        assert backoff_elapsed(retry_count=1, last_retry_at=last_retry) is True

    def test_exponential_backoff(self):
        """Backoff should be exponential: 5, 10, 20, 40, 80 minutes."""
        from context_service.pipelines.jobs.orphan_recovery import (
            BASE_BACKOFF_MINUTES,
            backoff_elapsed,
        )

        # retry_count=3 means wait 40 minutes (2^3 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=30)
        assert backoff_elapsed(retry_count=3, last_retry_at=last_retry) is False

        last_retry = datetime.now(UTC) - timedelta(minutes=45)
        assert backoff_elapsed(retry_count=3, last_retry_at=last_retry) is True


class TestFetchChainFromPostgres:
    """Tests for chain data fetching."""

    @pytest.mark.asyncio
    async def test_fetches_chain_steps(self):
        """Should fetch and format chain steps."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_step = MagicMock()
        mock_step.content = "step content"
        mock_step.step_index = 0
        mock_step.silo_id = uuid4()
        mock_result.scalars.return_value.all.return_value = [mock_step]
        mock_session.execute.return_value = mock_result

        with patch(
            "context_service.pipelines.jobs.orphan_recovery.get_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            from context_service.pipelines.jobs.orphan_recovery import (
                fetch_chain_from_postgres,
            )

            chain_id = uuid4()
            result = await fetch_chain_from_postgres(chain_id)

            assert result["chain_id"] == str(chain_id)
            assert result["step_count"] == 1
            assert result["steps"][0]["content"] == "step content"

    @pytest.mark.asyncio
    async def test_raises_on_no_steps(self):
        """Should raise ValueError when no steps found."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with patch(
            "context_service.pipelines.jobs.orphan_recovery.get_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            from context_service.pipelines.jobs.orphan_recovery import (
                fetch_chain_from_postgres,
            )

            with pytest.raises(ValueError, match="No steps found"):
                await fetch_chain_from_postgres(uuid4())
