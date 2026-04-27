"""Tests for evidence validation service."""
import pytest
from unittest.mock import AsyncMock, patch
from context_service.services.evidence import EvidenceValidator, EvidenceResult


@pytest.fixture
def validator():
    memgraph = AsyncMock()
    return EvidenceValidator(memgraph=memgraph)


@pytest.mark.asyncio
async def test_validate_node_ref_exists(validator):
    validator._memgraph.execute_query.return_value = [{"id": "abc-123"}]

    result = await validator.validate("node:abc-123", silo_id="silo-1")

    assert result.status == "valid"
    assert result.node_id == "abc-123"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_validate_node_ref_not_found(validator):
    validator._memgraph.execute_query.return_value = []

    result = await validator.validate("node:missing", silo_id="silo-1")

    assert result.status == "invalid"
    assert "not found" in result.reason.lower()


@pytest.mark.asyncio
async def test_validate_uri_reachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 200

        validator = EvidenceValidator(memgraph=AsyncMock())
        result = await validator.validate("https://example.com/doc", silo_id="silo-1")

        assert result.status == "valid"
        assert result.confidence == 0.7


@pytest.mark.asyncio
async def test_validate_uri_unreachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 404

        validator = EvidenceValidator(memgraph=AsyncMock())
        result = await validator.validate("https://example.com/missing", silo_id="silo-1")

        assert result.status == "invalid"


@pytest.mark.asyncio
async def test_validate_invalid_format(validator):
    result = await validator.validate("invalid-ref", silo_id="silo-1")

    assert result.status == "invalid"
    assert "format" in result.reason.lower()
