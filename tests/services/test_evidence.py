"""Tests for evidence validation service."""

from unittest.mock import AsyncMock, patch
from uuid import NAMESPACE_URL, uuid5

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
async def test_validate_urn_accepted(validator):
    result = await validator.validate(
        "urn:legal:case:california:supreme_court:edwards_v_arthur_andersen_llp:2008",
        silo_id="silo-1",
    )

    assert result.status == "valid"
    assert result.confidence == 0.85
    assert "URN" in result.reason


@pytest.mark.asyncio
async def test_validate_invalid_format(validator):
    result = await validator.validate("invalid-ref", silo_id="silo-1")

    assert result.status == "invalid"
    assert "format" in result.reason.lower()


@pytest.mark.asyncio
async def test_file_uri_creates_stub(validator):
    validator._store.execute_query.return_value = [{"id": "stub-id"}]
    uri = "file:///path/to/doc.md"
    silo_id = "silo-1"

    result = await validator.validate(uri, silo_id=silo_id)

    assert result.status == "valid"
    assert result.confidence == 0.9
    expected_id = str(uuid5(NAMESPACE_URL, f"{silo_id}:{uri}"))
    assert result.node_id == expected_id
    validator._store.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_urn_creates_stub(validator):
    validator._store.execute_query.return_value = [{"id": "stub-id"}]
    uri = "urn:isbn:0-123-45678-9"
    silo_id = "silo-1"

    result = await validator.validate(uri, silo_id=silo_id)

    assert result.status == "valid"
    assert result.confidence == 0.85
    expected_id = str(uuid5(NAMESPACE_URL, f"{silo_id}:{uri}"))
    assert result.node_id == expected_id
    validator._store.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_file_uri_stub_failure_hard_fails(validator):
    """Stub creation failure must reject the evidence, not silently store a lie."""
    validator._store.execute_query.side_effect = RuntimeError("DB error")
    uri = "file:///path/to/source.md"

    result = await validator.validate(uri, silo_id="silo-1")

    assert result.status == "invalid"
    assert result.node_id is None
