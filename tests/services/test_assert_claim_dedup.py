"""Unit tests for content-hash deduplication in assert_claim()."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context import ContextService
from context_service.services.models import ScopeContext


def _make_scope() -> ScopeContext:
    return ScopeContext(org_id="test-org", silo_id=uuid.uuid4())


def _make_service() -> tuple[ContextService, AsyncMock, AsyncMock]:
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock(return_value=[])
    memgraph.execute_query = AsyncMock(return_value=[])

    qdrant = AsyncMock()
    qdrant.upsert = AsyncMock(return_value=None)

    embedding = AsyncMock()
    embedding.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])

    svc = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
    )
    return svc, memgraph, qdrant


def _dedup_row(node_id: str, silo_id: str, content: str) -> dict[str, Any]:
    """Build a fake row as returned by the dedup MATCH query."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return {
        "id": node_id,
        "type": "Claim",
        "content": content,
        "silo_id": silo_id,
        "source_uri": None,
        "content_hash": content_hash,
        "created_at": "2026-01-01T00:00:00Z",
    }


_SETTINGS_PATCH = {
    "expansion_generation_enabled": False,
    "heat_ranking_enabled": False,
    "heat_weight": 0.0,
    "freshness_weight": 0.0,
    "freshness_sigma_days": 30,
}


class TestAssertClaimDedup:
    @pytest.mark.asyncio
    async def test_dedup_returns_same_node_id_on_second_call(self) -> None:
        """Second call with identical content returns the existing node ID."""
        svc, memgraph, _ = _make_service()
        scope = _make_scope()
        content = "The sky is blue"
        ev1 = [f"node:{uuid.uuid4()}"]

        # First call: no existing node -> store() is invoked.
        # store() itself calls execute_write once (CREATE) and execute_query
        # may be called for content-hash check (returns []).
        memgraph.execute_query.return_value = []

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(**_SETTINGS_PATCH)
            node1 = await svc.assert_claim(
                scope=scope,
                claim=content,
                evidence=ev1,
                source_type="observation",
            )

        first_id = node1.id

        # Second call: dedup query returns a matching row.
        dedup_row = _dedup_row(str(first_id), str(scope.silo_id), content)
        memgraph.execute_query.return_value = [dedup_row]

        ev2 = [f"node:{uuid.uuid4()}"]

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(**_SETTINGS_PATCH)
            node2 = await svc.assert_claim(
                scope=scope,
                claim=content,
                evidence=ev2,
                source_type="observation",
            )

        assert node2.id == first_id

    @pytest.mark.asyncio
    async def test_dedup_creates_evidence_edges_on_second_call(self) -> None:
        """Second call with same content still calls BATCH_CREATE_DERIVED_FROM_EDGES."""
        svc, memgraph, _ = _make_service()
        scope = _make_scope()
        content = "Photosynthesis converts light to energy"
        existing_id = str(uuid.uuid4())
        ev_node_id = str(uuid.uuid4())
        ev2 = [f"node:{ev_node_id}"]

        # Dedup query returns an existing node.
        dedup_row = _dedup_row(existing_id, str(scope.silo_id), content)
        memgraph.execute_query.return_value = [dedup_row]

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(**_SETTINGS_PATCH)
            node = await svc.assert_claim(
                scope=scope,
                claim=content,
                evidence=ev2,
                source_type="observation",
            )

        # Node ID should match the existing row.
        assert str(node.id) == existing_id

        # execute_write must have been called with the edge-creation query.
        from context_service.db.queries import BATCH_CREATE_DERIVED_FROM_EDGES

        write_calls = memgraph.execute_write.call_args_list
        edge_call = next(
            (c for c in write_calls if c.args and c.args[0] == BATCH_CREATE_DERIVED_FROM_EDGES),
            None,
        )
        assert edge_call is not None, (
            "BATCH_CREATE_DERIVED_FROM_EDGES was not called on the dedup path"
        )

        params = edge_call.args[1]
        assert params["claim_id"] == existing_id
        assert ev_node_id in params["ev_ids"]

    @pytest.mark.asyncio
    async def test_dedup_skips_edge_creation_when_no_node_evidence(self) -> None:
        """Dedup hit with no node: evidence refs skips execute_write for edges."""
        svc, memgraph, _ = _make_service()
        scope = _make_scope()
        content = "Water boils at 100 degrees"
        existing_id = str(uuid.uuid4())

        dedup_row = _dedup_row(existing_id, str(scope.silo_id), content)
        memgraph.execute_query.return_value = [dedup_row]

        # Evidence is a URI, not a node ref.
        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(**_SETTINGS_PATCH)
            node = await svc.assert_claim(
                scope=scope,
                claim=content,
                evidence=["https://example.com/source"],
                source_type="observation",
            )

        assert str(node.id) == existing_id

        from context_service.db.queries import BATCH_CREATE_DERIVED_FROM_EDGES

        write_calls = memgraph.execute_write.call_args_list
        edge_call = next(
            (c for c in write_calls if c.args and c.args[0] == BATCH_CREATE_DERIVED_FROM_EDGES),
            None,
        )
        assert edge_call is None, (
            "BATCH_CREATE_DERIVED_FROM_EDGES should not be called when evidence has no node refs"
        )
