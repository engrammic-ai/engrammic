from unittest.mock import AsyncMock

import pytest

from context_service.custodian.identities.custodian import CustodianIdentity


@pytest.mark.asyncio
async def test_custodian_detects_no_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []  # No existing facts

    custodian = CustodianIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-flash",
    )

    result = await custodian.check_contradiction("new-fact-id")
    assert result.has_contradiction is False
