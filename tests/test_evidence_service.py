"""Unit tests for EvidenceValidator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.services.evidence import EvidenceResult, EvidenceValidator


@pytest.fixture
def mock_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def validator(mock_store: AsyncMock) -> EvidenceValidator:
    return EvidenceValidator(store=mock_store, http_timeout=5.0)


class TestEvidenceResult:
    def test_default_values(self) -> None:
        result = EvidenceResult(status="valid")
        assert result.node_id is None
        assert result.confidence == 0.0
        assert result.reason is None

    def test_with_all_fields(self) -> None:
        result = EvidenceResult(
            status="valid",
            node_id="abc-123",
            confidence=0.95,
            reason="Validated",
        )
        assert result.status == "valid"
        assert result.node_id == "abc-123"
        assert result.confidence == 0.95


class TestValidateNodeRef:
    @pytest.mark.asyncio
    async def test_node_exists(self, validator: EvidenceValidator, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = [{"id": "abc-123"}]

        result = await validator.validate("node:abc-123", "silo-1")

        assert result.status == "valid"
        assert result.node_id == "abc-123"
        assert result.confidence == 1.0
        mock_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_node_not_found(self, validator: EvidenceValidator, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = []

        result = await validator.validate("node:missing-id", "silo-1")

        assert result.status == "invalid"
        assert "not found" in result.reason


class TestValidateUri:
    @pytest.mark.asyncio
    async def test_http_reachable(self, validator: EvidenceValidator) -> None:
        with patch("context_service.services.evidence.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(
                return_value=mock_response
            )

            result = await validator.validate("https://example.com/doc", "silo-1")

            assert result.status == "valid"
            assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_http_404(self, validator: EvidenceValidator) -> None:
        with patch("context_service.services.evidence.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 404
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(
                return_value=mock_response
            )

            result = await validator.validate("https://example.com/missing", "silo-1")

            assert result.status == "invalid"
            assert "404" in result.reason


class TestValidateFileUri:
    @pytest.mark.asyncio
    async def test_file_uri_accepted(self, validator: EvidenceValidator) -> None:
        result = await validator.validate("file:///path/to/doc.pdf", "silo-1")

        assert result.status == "valid"
        assert result.confidence == 0.9


class TestValidateInvalidFormat:
    @pytest.mark.asyncio
    async def test_invalid_format_rejected(self, validator: EvidenceValidator) -> None:
        result = await validator.validate("ftp://invalid", "silo-1")

        assert result.status == "invalid"
        assert "Invalid evidence format" in result.reason


class TestValidateAll:
    @pytest.mark.asyncio
    async def test_multiple_refs(self, validator: EvidenceValidator, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = [{"id": "node-1"}]

        results = await validator.validate_all(
            ["node:node-1", "file:///doc.pdf"],
            "silo-1",
        )

        assert len(results) == 2
        assert results[0].status == "valid"
        assert results[1].status == "valid"
