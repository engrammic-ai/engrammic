"""E2E tests for the 4-tool MCP surface.

All tests exercise the registered MCP tools via fastmcp Client, either against
a real running server or the in-process FastMCPTransport with fake stores.

Tool surface:
  context_store  -- unified write (memory/knowledge/wisdom/intelligence/meta)
  context_recall -- unified read (get by id, semantic search, graph traversal)
  context_link   -- create typed relationships between nodes
  context_admin  -- silo_list, close_session, provenance, history
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.e2e.conftest import call_result

pytestmark = pytest.mark.skip(reason="Uses internal tool names; pending verb promotion refactor")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def store(client: Any, layer: str, content: str, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool(
        "context_store",
        {"content": content, "layer": layer, **kwargs},
    )
    return call_result(raw)


async def recall(client: Any, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("context_recall", kwargs)
    return call_result(raw)


async def link(
    client: Any, from_node: str, to_node: str, relationship: str, **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "context_link",
        {"from_node": from_node, "to_node": to_node, "relationship": relationship, **kwargs},
    )
    return call_result(raw)


async def admin(client: Any, action: str, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("context_admin", {"action": action, **kwargs})
    return call_result(raw)


# ---------------------------------------------------------------------------
# 1. Store across all 5 layers
# ---------------------------------------------------------------------------


class TestStoreAllLayers:
    async def test_store_memory(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "memory", "Agent booted at t=0")
        assert result.get("layer") == "memory"
        assert "node_id" in result
        assert "created_at" in result

    async def test_store_memory_decay_classes(self, mcp_client: Any) -> None:
        for dc in ("ephemeral", "standard", "durable", "permanent"):
            result = await store(mcp_client, "memory", f"content for {dc}", decay_class=dc)
            assert "error" not in result, f"decay_class={dc!r} unexpectedly failed: {result}"
            assert result.get("layer") == "memory"

    async def test_store_knowledge(self, mcp_client: Any) -> None:
        mem = await store(mcp_client, "memory", "API docs state rate limit is 1000/min")
        ev_id = mem["node_id"]
        result = await store(
            mcp_client,
            "knowledge",
            "The API rate limit is 1000 req/min",
            evidence=[f"node:{ev_id}"],
            source_type="document",
            confidence=0.9,
        )
        assert result.get("layer") == "knowledge"
        assert "node_id" in result

    async def test_store_knowledge_missing_evidence(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "knowledge", "claim with no evidence")
        assert result.get("error") == "missing_evidence"

    async def test_store_knowledge_missing_source_type(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "knowledge",
            "claim without source_type",
            evidence=[f"node:{ev_id}"],
        )
        assert result.get("error") == "missing_source_type"

    async def test_store_wisdom(self, mcp_client: Any) -> None:
        node_a = str(uuid.uuid4())
        node_b = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "wisdom",
            "The system favours consistency over availability",
            about=[node_a, node_b],
            confidence=0.85,
            reasoning="Derived from CAP theorem applied to our shard config",
        )
        assert result.get("layer") == "wisdom"
        assert "node_id" in result

    async def test_store_wisdom_missing_about(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "wisdom", "belief without about")
        assert result.get("error") == "missing_about"

    async def test_store_intelligence(self, mcp_client: Any) -> None:
        steps = [
            {
                "step": 1,
                "reasoning": "Server returns X-RateLimit-Remaining",
            },
            {"step": 2, "reasoning": "Token bucket, replenishes hourly"},
        ]
        result = await store(
            mcp_client,
            "intelligence",
            "Rate limit is token-bucket, 1000/min",
            steps=steps,
        )
        assert result.get("layer") == "intelligence"
        assert "chain_id" in result
        assert result.get("steps_count") == 2

    async def test_store_intelligence_missing_steps(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "intelligence", "conclusion with no steps")
        assert result.get("error") == "missing_steps"

    async def test_store_meta(self, mcp_client: Any) -> None:
        ref_node = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "meta",
            "Confidence in rate-limit model shifted after new docs surfaced",
            observation_type="confidence_shift",
            about=[ref_node],
            confidence=0.7,
        )
        assert result.get("layer") == "meta"
        assert "node_id" in result

    async def test_store_meta_missing_observation_type(self, mcp_client: Any) -> None:
        ref_node = str(uuid.uuid4())
        result = await store(mcp_client, "meta", "obs", about=[ref_node])
        assert result.get("error") == "missing_observation_type"

    async def test_store_meta_missing_about(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "meta", "obs", observation_type="insight")
        assert result.get("error") == "missing_about"

    async def test_store_invalid_layer(self, mcp_client: Any) -> None:
        import pytest
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="literal_error"):
            await store(mcp_client, "invalid_layer", "content")


# ---------------------------------------------------------------------------
# 2. Store -> recall round-trip
# ---------------------------------------------------------------------------


class TestRecallRoundTrip:
    async def test_recall_by_node_id(self, mcp_client: Any) -> None:
        store_result = await store(mcp_client, "memory", "recall by ID test")
        assert "error" not in store_result

        node_id = store_result["node_id"]
        result = await recall(mcp_client, node_ids=[node_id])
        # Should return either nodes list or a result set without error
        assert "error" not in result

    async def test_recall_by_query(self, mcp_client: Any) -> None:
        await store(mcp_client, "memory", "the quick brown fox jumps")
        result = await recall(mcp_client, query="quick brown fox")
        assert "error" not in result
        assert "results" in result or "nodes" in result

    async def test_recall_by_query_with_top_k(self, mcp_client: Any) -> None:
        result = await recall(mcp_client, query="anything", top_k=3)
        assert "error" not in result

    async def test_recall_missing_both_inputs(self, mcp_client: Any) -> None:
        result = await recall(mcp_client)
        assert result.get("error") == "missing_input"

    async def test_recall_layer_filter(self, mcp_client: Any) -> None:
        await store(mcp_client, "memory", "memory layer content")
        result = await recall(mcp_client, query="memory layer", layers=["memory"])
        assert "error" not in result

    async def test_recall_time_travel(self, mcp_client: Any) -> None:
        past = "2024-01-01T00:00:00Z"
        store_result = await store(mcp_client, "memory", "time travel test")
        node_id = store_result["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of=past)
        assert "error" not in result or result.get("error") in (
            "not_found",
            "superseded",
        )

    async def test_recall_as_of_future(self, mcp_client: Any) -> None:
        future = "2099-12-31T23:59:59Z"
        store_result = await store(mcp_client, "memory", "future recall test")
        node_id = store_result["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of=future)
        assert "error" not in result


# ---------------------------------------------------------------------------
# 3. Store -> link -> graph traversal
# ---------------------------------------------------------------------------


class TestLinkAndGraph:
    async def test_link_two_nodes(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "node A")
        b = await store(mcp_client, "memory", "node B")
        assert "node_id" in a and "node_id" in b

        result = await link(mcp_client, a["node_id"], b["node_id"], "REFERENCES")
        assert "error" not in result
        assert "edge_id" in result
        assert result["from_node"] == a["node_id"]
        assert result["to_node"] == b["node_id"]
        assert result["relationship"] == "REFERENCES"

    async def test_link_all_relationship_types(self, mcp_client: Any) -> None:
        relationship_types = (
            "REFERENCES",
            "SUPPORTS",
            "CONTRADICTS",
            "DERIVED_FROM",
            "RELATED_TO",
            "CAUSES",
            "CORROBORATES",
            "PREVENTS",
        )
        a = await store(mcp_client, "memory", "source node")
        b = await store(mcp_client, "memory", "target node")
        for rel in relationship_types:
            result = await link(mcp_client, a["node_id"], b["node_id"], rel)
            assert "error" not in result, f"Unexpected error for relationship {rel!r}: {result}"

    async def test_link_invalid_relationship(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "node for invalid link")
        b = await store(mcp_client, "memory", "other node")
        result = await link(mcp_client, a["node_id"], b["node_id"], "NOT_A_RELATIONSHIP")
        assert result.get("error") == "invalid_relationship"
        assert "valid" in result

    async def test_link_with_weight(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "weighted source")
        b = await store(mcp_client, "memory", "weighted target")
        result = await link(mcp_client, a["node_id"], b["node_id"], "SUPPORTS", weight=5.0)
        assert "error" not in result

    async def test_link_invalid_weight(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "node x")
        b = await store(mcp_client, "memory", "node y")
        result = await link(mcp_client, a["node_id"], b["node_id"], "REFERENCES", weight=99.0)
        assert result.get("error") == "invalid_weight"

    async def test_link_with_note(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "annotated source")
        b = await store(mcp_client, "memory", "annotated target")
        result = await link(
            mcp_client, a["node_id"], b["node_id"], "RELATED_TO", note="added by e2e test"
        )
        assert "error" not in result

    async def test_graph_traversal_depth_1(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "graph seed node")
        b = await store(mcp_client, "memory", "graph neighbor")
        await link(mcp_client, a["node_id"], b["node_id"], "REFERENCES")

        result = await recall(mcp_client, node_ids=[a["node_id"]], depth=1)
        assert "error" not in result
        # Graph mode returns nodes + edges keys
        assert "nodes" in result or "edges" in result

    async def test_graph_traversal_depth_2(self, mcp_client: Any) -> None:
        root = await store(mcp_client, "memory", "root")
        mid = await store(mcp_client, "memory", "middle")
        leaf = await store(mcp_client, "memory", "leaf")
        await link(mcp_client, root["node_id"], mid["node_id"], "REFERENCES")
        await link(mcp_client, mid["node_id"], leaf["node_id"], "DERIVED_FROM")

        result = await recall(mcp_client, node_ids=[root["node_id"]], depth=2)
        assert "error" not in result

    async def test_query_graph_expansion(self, mcp_client: Any) -> None:
        # query + depth > 0 triggers graph expansion from query seed
        result = await recall(mcp_client, query="expand from query", depth=1)
        assert "error" not in result


# ---------------------------------------------------------------------------
# 4. Reasoning chain -> close_session
# ---------------------------------------------------------------------------


class TestReasoningChain:
    async def test_store_intelligence_and_close_session(self, mcp_client: Any) -> None:
        steps = [
            {"step": 1, "reasoning": "Observed in logs"},
            {"step": 2, "reasoning": "Consistent with docs"},
        ]
        store_result = await store(
            mcp_client,
            "intelligence",
            "Conclusion: system is stable",
            steps=steps,
        )
        assert "error" not in store_result
        chain_id = store_result["chain_id"]

        close_result = await admin(mcp_client, "close_session", ref=chain_id)
        # May error with feature_disabled if setting is off in test env;
        # accept that as a valid outcome.
        assert "error" not in close_result or close_result["error"] in (
            "feature_disabled",
            "chain_not_found",
        )

    async def test_close_session_missing_ref(self, mcp_client: Any) -> None:
        result = await admin(mcp_client, "close_session")
        assert result.get("error") == "missing_ref"

    async def test_store_reasoning_with_session_id(self, mcp_client: Any) -> None:
        steps = [{"step": 1, "reasoning": "Because A implies B"}]
        result = await store(
            mcp_client,
            "intelligence",
            "Conclusion B",
            steps=steps,
            # session_id passed via metadata workaround -- note: not a direct param on
            # context_store, so we test that it surfaces in the chain output.
        )
        assert "error" not in result
        assert "chain_id" in result

    async def test_already_closed_chain(self, mcp_client: Any) -> None:
        """Calling close_session twice on the same chain should return already_closed error."""
        from context_service.mcp.tools.context_admin import close_reasoning_chain
        from tests.fakes.fake_graph_store import FakeGraphStore

        store = FakeGraphStore()
        chain_id = str(uuid.uuid4())
        silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:already-closed"))

        # Seed a chain row that is already closed
        store.seed_query_result(
            [{"chain_id": chain_id, "steps": [], "session_state": "closed", "compacted": False}]
        )

        result = await close_reasoning_chain(store=store, chain_id=chain_id, silo_id=silo_id)
        assert result.get("error") == "already_closed"

    async def test_close_nonexistent_chain(self, mcp_client: Any) -> None:
        """Closing a chain that does not exist returns chain_not_found."""
        from context_service.mcp.tools.context_admin import close_reasoning_chain
        from tests.fakes.fake_graph_store import FakeGraphStore

        store = FakeGraphStore()
        # Seed empty result -- chain not found
        store.seed_query_result([])

        result = await close_reasoning_chain(
            store=store,
            chain_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:missing")),
        )
        assert result.get("error") == "chain_not_found"


# ---------------------------------------------------------------------------
# 5. Time-travel (as_of parameter)
# ---------------------------------------------------------------------------


class TestTimeTravel:
    async def test_recall_as_of_iso8601(self, mcp_client: Any) -> None:
        store_result = await store(mcp_client, "memory", "time-travel content")
        node_id = store_result["node_id"]

        # Query with an as_of timestamp after the node was created -- should find it
        result = await recall(mcp_client, node_ids=[node_id], as_of="2099-01-01T00:00:00Z")
        assert "error" not in result

    async def test_recall_as_of_before_creation(self, mcp_client: Any) -> None:
        store_result = await store(mcp_client, "memory", "future content")
        node_id = store_result["node_id"]

        # as_of is far in the past -- node should not appear (or return empty without error)
        result = await recall(mcp_client, node_ids=[node_id], as_of="2000-01-01T00:00:00Z")
        # Not an error -- just empty or superseded
        assert result.get("error") not in (
            "internal_error",
            "unexpected_error",
        )

    async def test_query_as_of_timestamp(self, mcp_client: Any) -> None:
        await store(mcp_client, "memory", "time-travel query target")
        result = await recall(
            mcp_client,
            query="time-travel query",
            as_of="2099-01-01T00:00:00Z",
        )
        assert "error" not in result

    @pytest.mark.xfail(
        reason="Fake context service state not shared between store/recall in e2e fixture"
    )
    async def test_recall_as_of_before_node_created(self, mcp_client: Any) -> None:
        """Query with as_of before node's valid_from returns not_yet_valid."""
        # Store a node (will have valid_from = now)
        store_result = await store(mcp_client, "memory", "future node content")
        node_id = store_result["node_id"]

        # Query with as_of in the past (before node existed)
        past = "2020-01-01T00:00:00Z"
        result = await recall(mcp_client, node_ids=[node_id], as_of=past)

        assert "nodes" in result
        assert len(result["nodes"]) == 1
        node_result = result["nodes"][0]
        assert node_result.get("error") == "not_yet_valid"
        assert node_result.get("node_id") == node_id
        assert "valid_from" in node_result

    async def test_recall_as_of_invalid_format(self, mcp_client: Any) -> None:
        """Invalid as_of format returns error."""
        store_result = await store(mcp_client, "memory", "test content")
        node_id = store_result["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of="not-a-date")

        assert result.get("error") == "invalid_as_of_format"


# ---------------------------------------------------------------------------
# 6. Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    async def test_invalid_decay_class(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "memory", "content", decay_class="bogus")
        assert result.get("error") == "invalid_decay_class"

    async def test_invalid_source_type(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "knowledge",
            "claim",
            evidence=[f"node:{ev_id}"],
            source_type="made_up",
        )
        assert result.get("error") == "invalid_source_type"

    async def test_invalid_confidence_below_zero(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "knowledge",
            "claim",
            evidence=[f"node:{ev_id}"],
            source_type="document",
            confidence=-0.1,
        )
        assert result.get("error") == "invalid_confidence"

    async def test_invalid_confidence_above_one(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "knowledge",
            "claim",
            evidence=[f"node:{ev_id}"],
            source_type="document",
            confidence=1.5,
        )
        assert result.get("error") == "invalid_confidence"

    async def test_invalid_observation_type(self, mcp_client: Any) -> None:
        ref_node = str(uuid.uuid4())
        result = await store(
            mcp_client,
            "meta",
            "observation",
            observation_type="not_valid",
            about=[ref_node],
        )
        assert result.get("error") == "invalid_observation_type"

    async def test_invalid_link_relationship(self, mcp_client: Any) -> None:
        a = await store(mcp_client, "memory", "src")
        b = await store(mcp_client, "memory", "dst")
        result = await link(mcp_client, a["node_id"], b["node_id"], "UNKNOWN")
        assert result.get("error") == "invalid_relationship"

    async def test_admin_unknown_action(self, mcp_client: Any) -> None:
        import pytest
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="literal_error"):
            await admin(mcp_client, "not_a_real_action")

    async def test_admin_provenance_missing_ref(self, mcp_client: Any) -> None:
        result = await admin(mcp_client, "provenance")
        assert result.get("error") == "missing_ref"

    async def test_admin_history_missing_ref(self, mcp_client: Any) -> None:
        result = await admin(mcp_client, "history")
        assert result.get("error") == "missing_ref"

    async def test_store_wisdom_empty_about_list(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "wisdom", "belief with empty about", about=[])
        assert result.get("error") == "missing_about"

    async def test_store_intelligence_empty_steps(self, mcp_client: Any) -> None:
        result = await store(mcp_client, "intelligence", "conclusion", steps=[])
        assert result.get("error") == "missing_steps"

    async def test_recall_no_args_returns_error(self, mcp_client: Any) -> None:
        result = await recall(mcp_client)
        assert result.get("error") == "missing_input"


# ---------------------------------------------------------------------------
# 7. Multi-agent visibility
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Uses in-process fakes; not compatible with real server testing")
class TestMultiAgentVisibility:
    async def test_two_agents_same_silo(self, e2e_org_id: str) -> None:
        """Two agents in the same org/silo should be able to see each other's nodes."""
        from unittest.mock import AsyncMock, patch

        from fastmcp import Client
        from fastmcp.client.transports import FastMCPTransport

        from tests.e2e.conftest import (
            _build_in_process_server,
            _make_auth,
            _make_fake_silo,
        )

        auth_a = _make_auth(e2e_org_id, agent_id="agent:alpha")
        auth_b = _make_auth(e2e_org_id, agent_id="agent:beta")
        silo = _make_fake_silo(e2e_org_id)

        # Both agents share the same underlying server instance
        server = _build_in_process_server(e2e_org_id)

        with (
            patch(
                "context_service.mcp.server.get_mcp_auth_context",
                new=AsyncMock(return_value=auth_a),
            ),
            patch(
                "context_service.services.silo.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.services.silo.ensure_silo",
                new=AsyncMock(return_value=silo),
            ),
        ):
            transport_a = FastMCPTransport(server)
            async with Client(transport_a) as client_a:
                store_result = await store(client_a, "memory", "agent alpha wrote this")
                assert "node_id" in store_result
                node_id = store_result["node_id"]

        with (
            patch(
                "context_service.mcp.server.get_mcp_auth_context",
                new=AsyncMock(return_value=auth_b),
            ),
            patch(
                "context_service.services.silo.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
        ):
            transport_b = FastMCPTransport(server)
            async with Client(transport_b) as client_b:
                result = await recall(client_b, node_ids=[node_id])
                assert "error" not in result

    async def test_agent_session_ids_distinct(self, mcp_client: Any) -> None:
        """Reasoning chains for different sessions should yield distinct chain_ids."""
        steps = [{"step": 1, "reasoning": "reason one"}]
        r1 = await store(mcp_client, "intelligence", "conclusion 1", steps=steps)
        r2 = await store(mcp_client, "intelligence", "conclusion 2", steps=steps)
        assert r1.get("chain_id") != r2.get("chain_id")


# ---------------------------------------------------------------------------
# 8. Silo isolation
# ---------------------------------------------------------------------------


class TestSiloIsolation:
    @pytest.mark.skip(
        reason="mcp_client_alt uses in-process fakes; not compatible with real server"
    )
    async def test_different_orgs_use_different_silos(
        self, mcp_client: Any, mcp_client_alt: Any
    ) -> None:
        """Nodes stored by org A should not be visible when queried under org B's silo."""
        store_result = await store(mcp_client, "memory", "org A secret data")
        node_id = store_result["node_id"]

        # The alt client's fake store is independent -- it has no knowledge of org A's node.
        result = await recall(mcp_client_alt, node_ids=[node_id])
        # Either returns empty nodes or a not_found error -- never the original content.
        nodes = result.get("nodes", [])
        # If nodes came back, none should have the content from org A
        for n in nodes:
            assert n.get("content") != "org A secret data"

    async def test_silo_list_returns_own_silo(self, mcp_client: Any) -> None:
        result = await admin(mcp_client, "silo_list")
        assert "error" not in result
        silos = result.get("silos", [])
        assert isinstance(silos, list)
        assert len(silos) >= 1

    @pytest.mark.skip(
        reason="mcp_client_alt uses in-process fakes; not compatible with real server"
    )
    async def test_silo_list_alt_org(self, mcp_client_alt: Any) -> None:
        result = await admin(mcp_client_alt, "silo_list")
        assert "error" not in result
        silos = result.get("silos", [])
        assert isinstance(silos, list)

    @pytest.mark.skip(
        reason="mcp_client_alt uses in-process fakes; not compatible with real server"
    )
    async def test_alt_org_silo_id_differs_from_primary(
        self, mcp_client: Any, mcp_client_alt: Any
    ) -> None:
        r1 = await admin(mcp_client, "silo_list")
        r2 = await admin(mcp_client_alt, "silo_list")
        assert "error" not in r1
        assert "error" not in r2
        silo_ids_1 = {s["silo_id"] for s in r1.get("silos", [])}
        silo_ids_2 = {s["silo_id"] for s in r2.get("silos", [])}
        assert silo_ids_1.isdisjoint(silo_ids_2), "Orgs share a silo ID -- silo isolation violated"


# ---------------------------------------------------------------------------
# 9. Admin actions
# ---------------------------------------------------------------------------


class TestAdminActions:
    async def test_silo_list(self, mcp_client: Any) -> None:
        result = await admin(mcp_client, "silo_list")
        assert "error" not in result
        assert "silos" in result

    async def test_provenance_for_node(self, mcp_client: Any) -> None:
        store_result = await store(mcp_client, "memory", "provenance test node")
        node_id = store_result["node_id"]
        result = await admin(mcp_client, "provenance", ref=node_id)
        assert "error" not in result

    async def test_history_for_node(self, mcp_client: Any) -> None:
        store_result = await store(mcp_client, "memory", "history test node")
        node_id = store_result["node_id"]
        result = await admin(mcp_client, "history", ref=node_id)
        assert "error" not in result

    async def test_close_session_feature_flag_disabled(self, mcp_client: Any) -> None:
        """When session_compaction_enabled is False, close_session returns feature_disabled."""
        from unittest.mock import patch

        from context_service.config.settings import Settings

        fake_settings = Settings.model_construct(
            session_compaction_enabled=False,
            auth_enabled=False,
            dev_org_id="test",
            dev_user_id="test",
        )
        with patch(
            "context_service.mcp.tools.context_admin.get_settings",
            return_value=fake_settings,
        ):
            result = await admin(mcp_client, "close_session", ref=str(uuid.uuid4()))
            assert result.get("error") == "feature_disabled"
