"""Test that revise_belief correctly threads cosine_distance to auto-reflection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_revise_belief_passes_cosine_distance_to_reflection():
    """Verify cosine_distance is passed through to make_revision_content."""
    from context_service.engine.revision import revise_belief

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(side_effect=[
        [{"belief_id": "old-belief", "content": "Old", "confidence": 0.9, "revision_count": 0}],
        [{"cluster_id": "cluster-1"}],
        [
            {"fact_id": "f1", "content": "Fact 1", "confidence": 0.95, "valid_from": "2026-01-01"},
            {"fact_id": "f2", "content": "Fact 2", "confidence": 0.90, "valid_from": "2026-01-02"},
            {"fact_id": "f3", "content": "Fact 3", "confidence": 0.85, "valid_from": "2026-01-03"},
        ],
    ])
    # async with store.transaction(): requires an async context manager
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    mock_store.transaction = MagicMock(return_value=tx_cm)
    mock_store.execute_write = AsyncMock()

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=("New belief content", {}))

    mock_embedding = AsyncMock()
    mock_embedding.embed = AsyncMock(return_value=[[0.1] * 768, [0.1] * 768, [0.1] * 768])

    with patch("context_service.engine.revision.create_auto_reflection") as mock_reflect, \
         patch("context_service.engine.revision.get_settings") as mock_settings, \
         patch("context_service.engine.revision.make_revision_content") as mock_content:

        settings = mock_settings.return_value
        settings.auto_reflect.enabled = True
        settings.auto_reflect.on_revision = True

        mock_content.return_value = "Belief revised with 15.0% drift"
        mock_reflect.return_value = None

        await revise_belief(
            store=mock_store,
            old_belief_id="old-belief",
            silo_id="test-silo",
            llm_client=mock_llm,
            embedding_client=mock_embedding,
            cosine_distance=0.15,
        )

        mock_content.assert_called_once()
        call_kwargs = mock_content.call_args.kwargs
        assert call_kwargs["magnitude_pct"] == pytest.approx(15.0, rel=0.01)
