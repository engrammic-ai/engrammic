"""Integration tests for failure mode coverage.

Covers:
- Extraction LLM unavailable (error propagation)
- Memgraph transient ServiceUnavailable (retry recovery)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable

from context_service.extraction.service import ExtractionError, ExtractionService
from context_service.stores.memgraph import MemgraphClient, MemgraphOperationError

# ============================================================================
# LLM Unavailable during extraction
# ============================================================================


@pytest.mark.integration
class TestExtractionLLMUnavailable:
    """Extraction fails gracefully when the LLM provider raises."""

    async def test_llm_network_error_raises_extraction_error(self) -> None:
        """LLM raising a network error is wrapped as ExtractionError."""
        mock_llm = AsyncMock()
        mock_llm.extract_structured = AsyncMock(side_effect=OSError("Connection refused"))

        service = ExtractionService.llm_only(mock_llm)

        with pytest.raises(ExtractionError, match="LLM extraction failed"):
            await service.extract("Some content to extract from.")

    async def test_llm_timeout_raises_extraction_error(self) -> None:
        """LLM raising a timeout is wrapped as ExtractionError."""
        mock_llm = AsyncMock()
        mock_llm.extract_structured = AsyncMock(side_effect=TimeoutError())

        service = ExtractionService.llm_only(mock_llm)

        with pytest.raises(ExtractionError):
            await service.extract("Content that will time out.")

    async def test_llm_provider_error_raises_extraction_error(self) -> None:
        """LLM raising a provider-level exception is wrapped as ExtractionError."""
        mock_llm = AsyncMock()
        mock_llm.extract_structured = AsyncMock(side_effect=RuntimeError("API rate limit exceeded"))

        service = ExtractionService.llm_only(mock_llm)

        with pytest.raises(ExtractionError, match="LLM extraction failed"):
            await service.extract("Some content.")

    async def test_llm_called_once_no_retry_on_error(self) -> None:
        """Extraction does not retry on LLM failure (retry is not the LLM's concern)."""
        mock_llm = AsyncMock()
        mock_llm.extract_structured = AsyncMock(side_effect=OSError("Unreachable"))

        service = ExtractionService.llm_only(mock_llm)

        with pytest.raises(ExtractionError):
            await service.extract("Content.")

        # extract_structured called exactly once; no retry loop at this layer
        mock_llm.extract_structured.assert_called_once()


# ============================================================================
# Memgraph transient ServiceUnavailable retry
# ============================================================================


@pytest.mark.integration
class TestMemgraphTransientRetry:
    """MemgraphClient retry policy recovers from a single transient failure."""

    async def test_read_retries_on_service_unavailable(self) -> None:
        """execute_query retries and succeeds after one ServiceUnavailable."""
        call_count = 0

        async def _flaky_run(query: str, params: dict) -> object:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ServiceUnavailable("transient: attempt 1")
            # Return a fake result object with .data()
            mock_result = AsyncMock()
            mock_result.data = AsyncMock(return_value=[{"n": 1}])
            return mock_result

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=_flaky_run)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()

        client = MemgraphClient(mock_driver)

        with patch.object(client, "session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.execute_query("MATCH (n) RETURN n LIMIT 1")

        assert result == [{"n": 1}]
        assert call_count == 2

    async def test_write_retries_on_service_unavailable(self) -> None:
        """execute_write retries and succeeds after one ServiceUnavailable."""
        call_count = 0

        async def _flaky_execute_write(fn: object, *args: object) -> list[dict]:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ServiceUnavailable("transient: attempt 1")
            return [{"id": "abc"}]

        mock_session = AsyncMock()
        mock_session.execute_write = AsyncMock(side_effect=_flaky_execute_write)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        client = MemgraphClient(mock_driver)

        with patch.object(client, "session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.execute_write(
                "CREATE (n:Test {id: $id}) RETURN n.id AS id",
                {"id": "abc"},
            )

        assert result == [{"id": "abc"}]
        assert call_count == 2

    async def test_exhausted_retries_raise_memgraph_operation_error(self) -> None:
        """All retry attempts failing raises MemgraphOperationError."""
        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=ServiceUnavailable("permanently down"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        client = MemgraphClient(mock_driver)

        with patch.object(client, "session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(MemgraphOperationError, match="Database unavailable"):
                await client.execute_query("MATCH (n) RETURN n")
