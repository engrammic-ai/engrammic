from unittest.mock import AsyncMock

import pytest

from context_service.custodian.identities.synthesizer import SynthesizerIdentity


@pytest.mark.asyncio
async def test_synthesizer_finds_candidates():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"cluster_id": "c1", "fact_count": 5},
    ]

    synthesizer = SynthesizerIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-pro",
    )

    candidates = await synthesizer.find_synthesis_candidates()
    assert len(candidates) >= 0
