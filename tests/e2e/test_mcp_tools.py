"""E2E tests for MCP verb surface.

All tests exercise the registered MCP tools via fastmcp Client.

Tool surface:
  remember  -- store observation (memory layer)
  learn     -- store claim with evidence (knowledge layer)
  believe   -- store commitment (wisdom layer)
  reason    -- record reasoning chain (intelligence layer)
  reflect   -- record meta-observation (meta layer)
  recall    -- retrieve nodes
  link      -- create relationships
  trace     -- trace provenance
  forget    -- request deletion
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.e2e.conftest import call_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def remember(client: Any, content: str, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("remember", {"content": content, **kwargs})
    return call_result(raw)


async def learn(
    client: Any, claim: str, evidence: list[str], source: str = "document", **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "learn", {"claim": claim, "evidence": evidence, "source": source, **kwargs}
    )
    return call_result(raw)


async def believe(
    client: Any, belief: str, about: list[str], **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "believe", {"belief": belief, "about": about, **kwargs}
    )
    return call_result(raw)


async def reason(
    client: Any, steps: list[dict[str, Any]], conclusion: str | None = None, **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "reason", {"steps": steps, "conclusion": conclusion, **kwargs}
    )
    return call_result(raw)


async def reflect(
    client: Any, observation: str, type: str, about: list[str], **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "reflect", {"observation": observation, "type": type, "about": about, **kwargs}
    )
    return call_result(raw)


async def recall(client: Any, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("recall", kwargs)
    return call_result(raw)


async def link(
    client: Any, from_node: str, to_node: str, relationship: str, **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "link",
        {"from_node": from_node, "to_node": to_node, "relationship": relationship, **kwargs},
    )
    return call_result(raw)


async def trace_provenance(client: Any, node_id: str) -> dict[str, Any]:
    raw = await client.call_tool("trace", {"node_id": node_id})
    return call_result(raw)


# ---------------------------------------------------------------------------
# 1. Store across all layers
# ---------------------------------------------------------------------------


class TestStoreAllLayers:
    async def test_store_memory(self, mcp_client: Any) -> None:
        result = await remember(mcp_client, "Agent booted at t=0")
        assert result.get("layer") == "memory"
        assert "node_id" in result
        assert "created_at" in result

    async def test_store_memory_decay_classes(self, mcp_client: Any) -> None:
        for dc in ("ephemeral", "standard", "durable", "permanent"):
            result = await remember(mcp_client, f"content for {dc}", decay=dc)
            assert "error" not in result, f"decay={dc!r} unexpectedly failed: {result}"
            assert result.get("layer") == "memory"

    async def test_store_knowledge(self, mcp_client: Any) -> None:
        mem = await remember(mcp_client, "API docs state rate limit is 1000/min")
        ev_id = mem["node_id"]
        result = await learn(
            mcp_client,
            "The API rate limit is 1000 req/min",
            evidence=[f"node:{ev_id}"],
            source="document",
            confidence=0.9,
        )
        assert result.get("layer") == "knowledge"
        assert "node_id" in result

    async def test_store_knowledge_missing_evidence(self, mcp_client: Any) -> None:
        result = await learn(
            mcp_client,
            "claim with empty evidence",
            evidence=[],
            source="document",
        )
        assert result.get("error") == "missing_evidence"

    async def test_store_knowledge_missing_source_type(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await learn(
            mcp_client,
            "claim without source",
            evidence=[f"node:{ev_id}"],
            source="made_up_source",
        )
        assert result.get("error") == "invalid_source_type"

    async def test_store_wisdom(self, mcp_client: Any) -> None:
        node_a = str(uuid.uuid4())
        node_b = str(uuid.uuid4())
        result = await believe(
            mcp_client,
            "The system favours consistency over availability",
            about=[node_a, node_b],
            confidence=0.85,
            reasoning="Derived from CAP theorem applied to our shard config",
        )
        assert result.get("layer") == "wisdom"
        assert "node_id" in result

    async def test_store_wisdom_missing_about(self, mcp_client: Any) -> None:
        result = await believe(mcp_client, "belief without about", about=[])
        assert result.get("error") == "missing_about"

    async def test_store_intelligence(self, mcp_client: Any) -> None:
        steps = [
            {
                "step": 1,
                "reasoning": "Server returns X-RateLimit-Remaining",
            },
            {"step": 2, "reasoning": "Token bucket, replenishes hourly"},
        ]
        result = await reason(
            mcp_client,
            steps=steps,
            conclusion="Rate limit is token-bucket, 1000/min",
        )
        assert "chain_id" in result
        assert "error" not in result

    async def test_store_intelligence_missing_steps(self, mcp_client: Any) -> None:
        raw = await mcp_client.call_tool(
            "reason", {"steps": [], "conclusion": "conclusion with no steps"}
        )
        result = call_result(raw)
        assert result.get("error") == "missing_steps"

    async def test_store_meta(self, mcp_client: Any) -> None:
        ref_node = str(uuid.uuid4())
        result = await reflect(
            mcp_client,
            observation="Confidence in rate-limit model shifted after new docs surfaced",
            type="confidence_shift",
            about=[ref_node],
            confidence=0.7,
        )
        assert "node_id" in result
        assert "error" not in result

    async def test_store_meta_missing_observation_type(self, mcp_client: Any) -> None:
        from fastmcp.exceptions import ToolError

        ref_node = str(uuid.uuid4())
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "reflect", {"observation": "obs", "about": [ref_node]}
            )

    async def test_store_meta_missing_about(self, mcp_client: Any) -> None:
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "reflect", {"observation": "obs", "type": "pattern"}
            )


# ---------------------------------------------------------------------------
# 2. Store -> recall round-trip
# ---------------------------------------------------------------------------


class TestRecallRoundTrip:
    async def test_recall_by_node_id(self, mcp_client: Any) -> None:
        stored = await remember(mcp_client, "recall by ID test")
        assert "error" not in stored

        node_id = stored["node_id"]
        result = await recall(mcp_client, node_ids=[node_id])
        assert "error" not in result

    async def test_recall_by_query(self, mcp_client: Any) -> None:
        await remember(mcp_client, "the quick brown fox jumps")
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
        await remember(mcp_client, "memory layer content")
        result = await recall(mcp_client, query="memory layer", layers=["memory"])
        assert "error" not in result

    async def test_recall_time_travel(self, mcp_client: Any) -> None:
        past = "2024-01-01T00:00:00Z"
        stored = await remember(mcp_client, "time travel test")
        node_id = stored["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of=past)
        assert "error" not in result or result.get("error") in (
            "not_found",
            "superseded",
        )

    async def test_recall_as_of_future(self, mcp_client: Any) -> None:
        future = "2099-12-31T23:59:59Z"
        stored = await remember(mcp_client, "future recall test")
        node_id = stored["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of=future)
        assert "error" not in result


# ---------------------------------------------------------------------------
# 3. Store -> link -> graph traversal
# ---------------------------------------------------------------------------


class TestLinkAndGraph:
    async def test_link_two_nodes(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "node A")
        b = await remember(mcp_client, "node B")
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
        a = await remember(mcp_client, "source node")
        b = await remember(mcp_client, "target node")
        for rel in relationship_types:
            result = await link(mcp_client, a["node_id"], b["node_id"], rel)
            assert "error" not in result, f"Unexpected error for relationship {rel!r}: {result}"

    async def test_link_invalid_relationship(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "node for invalid link")
        b = await remember(mcp_client, "other node")
        result = await link(mcp_client, a["node_id"], b["node_id"], "NOT_A_RELATIONSHIP")
        assert result.get("error") == "invalid_relationship"
        assert "valid" in result

    async def test_link_with_weight(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "weighted source")
        b = await remember(mcp_client, "weighted target")
        result = await link(mcp_client, a["node_id"], b["node_id"], "SUPPORTS", weight=5.0)
        assert "error" not in result

    async def test_link_invalid_weight(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "node x")
        b = await remember(mcp_client, "node y")
        result = await link(mcp_client, a["node_id"], b["node_id"], "REFERENCES", weight=99.0)
        assert result.get("error") == "invalid_weight"

    async def test_link_with_note(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "annotated source")
        b = await remember(mcp_client, "annotated target")
        result = await link(
            mcp_client, a["node_id"], b["node_id"], "RELATED_TO", note="added by e2e test"
        )
        assert "error" not in result

    async def test_graph_traversal_depth_1(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "graph seed node")
        b = await remember(mcp_client, "graph neighbor")
        await link(mcp_client, a["node_id"], b["node_id"], "REFERENCES")

        result = await recall(mcp_client, node_ids=[a["node_id"]], depth=1)
        assert "error" not in result
        # Graph mode returns nodes + edges keys
        assert "nodes" in result or "edges" in result

    async def test_graph_traversal_depth_2(self, mcp_client: Any) -> None:
        root = await remember(mcp_client, "root")
        mid = await remember(mcp_client, "middle")
        leaf = await remember(mcp_client, "leaf")
        await link(mcp_client, root["node_id"], mid["node_id"], "REFERENCES")
        await link(mcp_client, mid["node_id"], leaf["node_id"], "DERIVED_FROM")

        result = await recall(mcp_client, node_ids=[root["node_id"]], depth=2)
        assert "error" not in result

    async def test_query_graph_expansion(self, mcp_client: Any) -> None:
        # query + depth > 0 triggers graph expansion from query seed
        result = await recall(mcp_client, query="expand from query", depth=1)
        assert "error" not in result


# ---------------------------------------------------------------------------
# 4. Reasoning chain
# ---------------------------------------------------------------------------


class TestReasoningChain:
    async def test_store_intelligence(self, mcp_client: Any) -> None:
        steps = [
            {"step": 1, "reasoning": "Observed in logs"},
            {"step": 2, "reasoning": "Consistent with docs"},
        ]
        result = await reason(
            mcp_client,
            steps=steps,
            conclusion="Conclusion: system is stable",
        )
        assert "error" not in result
        assert "chain_id" in result

    async def test_store_reasoning_with_conclusion(self, mcp_client: Any) -> None:
        steps = [{"step": 1, "reasoning": "Because A implies B"}]
        result = await reason(
            mcp_client,
            steps=steps,
            conclusion="Conclusion B",
        )
        assert "error" not in result
        assert "chain_id" in result

    @pytest.mark.skip(reason="close_reasoning_chain removed with context_admin; no replacement")
    async def test_already_closed_chain(self, mcp_client: Any) -> None:
        """Calling close_session twice on the same chain should return already_closed error."""
        pass

    @pytest.mark.skip(reason="close_reasoning_chain removed with context_admin; no replacement")
    async def test_close_nonexistent_chain(self, mcp_client: Any) -> None:
        """Closing a chain that does not exist returns chain_not_found."""
        pass


# ---------------------------------------------------------------------------
# 5. Time-travel (as_of parameter)
# ---------------------------------------------------------------------------


class TestTimeTravel:
    async def test_recall_as_of_iso8601(self, mcp_client: Any) -> None:
        stored = await remember(mcp_client, "time-travel content")
        node_id = stored["node_id"]

        # Query with an as_of timestamp after the node was created -- should find it
        result = await recall(mcp_client, node_ids=[node_id], as_of="2099-01-01T00:00:00Z")
        assert "error" not in result

    async def test_recall_as_of_before_creation(self, mcp_client: Any) -> None:
        stored = await remember(mcp_client, "future content")
        node_id = stored["node_id"]

        # as_of is far in the past -- node should not appear (or return empty without error)
        result = await recall(mcp_client, node_ids=[node_id], as_of="2000-01-01T00:00:00Z")
        # Not an error -- just empty or superseded
        assert result.get("error") not in (
            "internal_error",
            "unexpected_error",
        )

    async def test_query_as_of_timestamp(self, mcp_client: Any) -> None:
        await remember(mcp_client, "time-travel query target")
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
        stored = await remember(mcp_client, "future node content")
        node_id = stored["node_id"]

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
        stored = await remember(mcp_client, "test content")
        node_id = stored["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of="not-a-date")

        assert result.get("error") == "invalid_as_of_format"


# ---------------------------------------------------------------------------
# 6. Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    async def test_invalid_decay_class(self, mcp_client: Any) -> None:
        result = await remember(mcp_client, "content", decay="bogus")
        assert result.get("error") == "invalid_decay_class"

    async def test_invalid_source_type(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await learn(
            mcp_client,
            "claim",
            evidence=[f"node:{ev_id}"],
            source="made_up",
        )
        assert result.get("error") == "invalid_source_type"

    async def test_invalid_confidence_below_zero(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await learn(
            mcp_client,
            "claim",
            evidence=[f"node:{ev_id}"],
            source="document",
            confidence=-0.1,
        )
        assert result.get("error") == "invalid_confidence"

    async def test_invalid_confidence_above_one(self, mcp_client: Any) -> None:
        ev_id = str(uuid.uuid4())
        result = await learn(
            mcp_client,
            "claim",
            evidence=[f"node:{ev_id}"],
            source="document",
            confidence=1.5,
        )
        assert result.get("error") == "invalid_confidence"

    async def test_invalid_observation_type(self, mcp_client: Any) -> None:
        ref_node = str(uuid.uuid4())
        result = await reflect(
            mcp_client,
            observation="observation",
            type="not_valid",
            about=[ref_node],
        )
        assert result.get("error") == "invalid_observation_type"

    async def test_invalid_link_relationship(self, mcp_client: Any) -> None:
        a = await remember(mcp_client, "src")
        b = await remember(mcp_client, "dst")
        result = await link(mcp_client, a["node_id"], b["node_id"], "UNKNOWN")
        assert result.get("error") == "invalid_relationship"

    async def test_recall_no_args_returns_error(self, mcp_client: Any) -> None:
        result = await recall(mcp_client)
        assert result.get("error") == "missing_input"

    async def test_store_wisdom_empty_about_list(self, mcp_client: Any) -> None:
        result = await believe(mcp_client, "belief with empty about", about=[])
        assert result.get("error") == "missing_about"

    async def test_store_intelligence_empty_steps(self, mcp_client: Any) -> None:
        raw = await mcp_client.call_tool(
            "reason", {"steps": [], "conclusion": "conclusion"}
        )
        result = call_result(raw)
        assert result.get("error") == "missing_steps"


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
                stored = await remember(client_a, "agent alpha wrote this")
                assert "node_id" in stored
                node_id = stored["node_id"]

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
        r1 = await reason(mcp_client, steps=steps, conclusion="conclusion 1")
        r2 = await reason(mcp_client, steps=steps, conclusion="conclusion 2")
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
        stored = await remember(mcp_client, "org A secret data")
        node_id = stored["node_id"]

        # The alt client's fake store is independent -- it has no knowledge of org A's node.
        result = await recall(mcp_client_alt, node_ids=[node_id])
        # Either returns empty nodes or a not_found error -- never the original content.
        nodes = result.get("nodes", [])
        # If nodes came back, none should have the content from org A
        for n in nodes:
            assert n.get("content") != "org A secret data"

    @pytest.mark.skip(
        reason="mcp_client_alt uses in-process fakes; not compatible with real server"
    )
    async def test_silo_list_alt_org(self, mcp_client_alt: Any) -> None:
        result = await recall(mcp_client_alt, query="anything")
        assert "error" not in result

    @pytest.mark.skip(
        reason="mcp_client_alt uses in-process fakes; not compatible with real server"
    )
    async def test_alt_org_silo_id_differs_from_primary(
        self, mcp_client: Any, mcp_client_alt: Any
    ) -> None:
        r1 = await remember(mcp_client, "org A marker")
        r2 = await remember(mcp_client_alt, "org B marker")
        # Nodes from different orgs should have different silo_ids in their metadata
        assert r1.get("node_id") != r2.get("node_id")


# ---------------------------------------------------------------------------
# 9. Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    async def test_provenance_for_node(self, mcp_client: Any) -> None:
        stored = await remember(mcp_client, "provenance test node")
        node_id = stored["node_id"]
        result = await trace_provenance(mcp_client, node_id)
        assert "error" not in result

    async def test_provenance_missing_node_id(self, mcp_client: Any) -> None:
        raw = await mcp_client.call_tool("trace", {"node_id": ""})
        result = call_result(raw)
        assert result.get("error") == "missing_node_id"
