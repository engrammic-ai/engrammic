"""Tests for v1.4 phase 4d: Hierarchical meta-memory."""

import uuid

import pytest

from context_service.services.models import ScopeContext


class TestHierarchicalReflection:
    """reflection Memory nodes can target other reflection Memory nodes."""

    @pytest.mark.asyncio
    async def test_reflect_on_non_meta_sets_depth_1(self) -> None:
        """Reflecting on a non-reflection Memory node node sets reflection_depth=1."""
        from unittest.mock import AsyncMock, MagicMock

        from context_service.services.context import ContextService

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(return_value=[])
        mock_store.execute_write = AsyncMock(return_value=[{"id": "meta-1"}])

        svc = ContextService(memgraph=mock_store, qdrant=MagicMock())
        scope = ScopeContext(org_id="org-1", silo_id=uuid.uuid4())

        result = await svc.reflect(
            scope=scope,
            observation="This is interesting",
            observation_type="insight",
            about=["node-123"],
            agent_id="agent:test",
        )

        assert result is not None
        # Check the first execute_write call (node creation) has reflection_depth in extra_props
        calls = mock_store.execute_write.call_args_list
        assert len(calls) >= 1
        # First call is the CREATE node query
        create_call_params = calls[0][0][1]
        extra_props = create_call_params.get("extra_props", {})
        assert extra_props.get("reflection_depth") == 1
        assert extra_props.get("decay_class") == "permanent"

    @pytest.mark.asyncio
    async def test_reflect_on_meta_observation_increments_depth(self) -> None:
        """Reflecting on a reflection Memory node of depth 1 sets reflection_depth=2."""
        from unittest.mock import AsyncMock, MagicMock

        from context_service.services.context import ContextService

        mock_store = MagicMock()
        # First query returns the target reflection Memory node with depth 1
        mock_store.execute_query = AsyncMock(
            return_value=[{"id": "meta-target", "reflection_depth": 1}]
        )
        mock_store.execute_write = AsyncMock(return_value=[{"id": "meta-2"}])

        svc = ContextService(memgraph=mock_store, qdrant=MagicMock())
        scope = ScopeContext(org_id="org-1", silo_id=uuid.uuid4())

        result = await svc.reflect(
            scope=scope,
            observation="I notice I keep reflecting on this",
            observation_type="pattern",
            about=["meta-target"],
            agent_id="agent:test",
        )

        assert result is not None
        calls = mock_store.execute_write.call_args_list
        assert len(calls) >= 1
        create_call_params = calls[0][0][1]
        extra_props = create_call_params.get("extra_props", {})
        assert extra_props.get("reflection_depth") == 2
