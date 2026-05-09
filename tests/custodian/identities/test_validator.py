from unittest.mock import AsyncMock

import pytest

from context_service.custodian.identities.validator import ValidatorIdentity


@pytest.mark.asyncio
async def test_validator_passes_valid_hypothesis():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"premise_id": "p1", "exists": True},
        {"premise_id": "p2", "exists": True},
    ]

    validator = ValidatorIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-pro",
        timeout_seconds=5,
    )

    result = await validator.validate_premises(["p1", "p2"])
    assert result.valid is True
    assert result.validation_skipped is False
