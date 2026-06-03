"""Integration tests validating MCP -> brain transaction cutover."""

from __future__ import annotations

import pytest

from context_service.reactions.events import ReactionEventType
from context_service.sage.transactions import store_claim, store_memory
from tests.fakes.fake_graph_store import FakeGraphStore


@pytest.fixture
def fake_graph_store() -> FakeGraphStore:
    return FakeGraphStore()


@pytest.fixture
def test_silo_id() -> str:
    return "test-silo-cutover"


@pytest.mark.integration
class TestBrainCutover:
    """Verify brain transactions emit correct events."""

    async def test_store_memory_emits_embedding_event(
        self, fake_graph_store: FakeGraphStore, test_silo_id: str
    ) -> None:
        """store_memory should emit COMPUTE_EMBEDDING reaction."""
        result, events = await store_memory(
            store=fake_graph_store,
            content="Test observation",
            silo_id=test_silo_id,
            agent_id="test-agent",
            emit=False,
        )

        assert result.node_id is not None
        event_types = [e.event_type for e in events]
        assert ReactionEventType.COMPUTE_EMBEDDING in event_types

    async def test_store_memory_with_meta_layer(
        self, fake_graph_store: FakeGraphStore, test_silo_id: str
    ) -> None:
        """store_memory with layer=meta should work for reflect."""
        result, events = await store_memory(
            store=fake_graph_store,
            content="I was wrong about X",
            silo_id=test_silo_id,
            agent_id="test-agent",
            layer="meta",
            emit=False,
        )

        assert result.node_id is not None

    async def test_store_claim_emits_events(
        self, fake_graph_store: FakeGraphStore, test_silo_id: str
    ) -> None:
        """store_claim should emit embedding event."""
        result, events = await store_claim(
            store=fake_graph_store,
            content="The API uses OAuth2",
            evidence_refs=["file://docs/api.md"],
            silo_id=test_silo_id,
            agent_id="test-agent",
            source_tier="documentation",
            emit=False,
        )

        assert result.node_id is not None
        event_types = [e.event_type for e in events]
        assert ReactionEventType.COMPUTE_EMBEDDING in event_types
