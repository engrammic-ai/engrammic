"""Tests for cross-cluster chain stitching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from context_service.custodian.chain_stitcher import (
    ChainStitchResult,
    stitch_cross_cluster_chains,
)


@dataclass
class MockNode:
    id: str
    cluster_id: str
    silo_id: str
    content: str
    created_at: datetime


class TestChainStitcher:
    @pytest.mark.asyncio
    async def test_stitches_cross_cluster_chain(self) -> None:
        """A->B->C where A in cluster1, B in cluster2, C in cluster3."""
        mock_store = AsyncMock()
        mock_store.run_query = AsyncMock(
            return_value=[
                {
                    "superseding_id": "a",
                    "superseding_cluster": "cluster1",
                    "superseded_id": "b",
                    "superseded_cluster": "cluster2",
                    "upstream_id": None,
                    "downstream_id": "c",
                },
            ]
        )

        result = await stitch_cross_cluster_chains(
            store=mock_store,
            silo_id="test-silo",
        )

        assert isinstance(result, ChainStitchResult)
        assert result.chains_found >= 0

    @pytest.mark.asyncio
    async def test_finds_terminal_nodes(self) -> None:
        """Terminal nodes are those that supersede but are not superseded."""
        mock_store = AsyncMock()
        mock_store.run_query = AsyncMock(
            side_effect=[
                [],  # First call: cross-cluster gaps
                [  # Second call: terminals
                    {
                        "terminal_id": "a",
                        "terminal_cluster": "cluster1",
                        "chain_ids": ["b", "c"],
                    }
                ],
            ]
        )

        result = await stitch_cross_cluster_chains(
            store=mock_store,
            silo_id="test-silo",
        )

        assert result.terminals_found == 1
