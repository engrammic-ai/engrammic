"""Tests for evidence validation service."""

from unittest.mock import AsyncMock, patch

import pytest

from context_service.services.evidence import EvidenceValidator


@pytest.fixture
def validator():
    store = AsyncMock()
    return EvidenceValidator(store=store)


@pytest.mark.asyncio
async def test_validate_node_ref_exists(validator):
    validator._store.execute_query.return_value = [{"id": "abc-123"}]

    result = await validator.validate("node:abc-123", silo_id="silo-1")

    assert result.status == "valid"
    assert result.node_id == "abc-123"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_validate_node_ref_not_found(validator):
    validator._store.execute_query.return_value = []

    result = await validator.validate("node:missing", silo_id="silo-1")

    assert result.status == "invalid"
    assert "not found" in result.reason.lower()


@pytest.mark.asyncio
async def test_validate_uri_reachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 200

        validator = EvidenceValidator(store=AsyncMock())
        result = await validator.validate("https://example.com/doc", silo_id="silo-1")

        assert result.status == "valid"
        assert result.confidence == 0.7


@pytest.mark.asyncio
async def test_validate_uri_unreachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 404

        validator = EvidenceValidator(store=AsyncMock())
        result = await validator.validate("https://example.com/missing", silo_id="silo-1")

        assert result.status == "invalid"


@pytest.mark.asyncio
async def test_validate_invalid_format(validator):
    result = await validator.validate("invalid-ref", silo_id="silo-1")

    assert result.status == "invalid"
    assert "format" in result.reason.lower()
