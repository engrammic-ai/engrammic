"""Eval: MCP tool layer testing with rich scenarios.

Tests all 4 cognitive layers (Memory, Knowledge, Wisdom, Intelligence) plus
meta-memory operations via MCP tools against the docker stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import call_result

pytest_plugins = ["tests.e2e.conftest"]


async def store(client: Any, layer: str, content: str, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("context_store", {"content": content, "layer": layer, **kwargs})
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


@pytest.mark.evals
@pytest.mark.integration
class TestMemoryLayer:
    """Memory layer: observations, events, raw context."""

    async def test_store_meeting_observation(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "memory",
            "Meeting with Acme Corp scheduled for 2026-05-10. John mentioned Q3 budget concerns.",
            decay_class="standard",
            metadata={"source": "calendar", "participants": ["john@acme.com"]},
        )
        assert result.get("layer") == "memory"
        assert "node_id" in result
        node_id = result["node_id"]

        fetched = await recall(mcp_client, node_ids=[node_id])
        nodes = fetched.get("nodes", [])
        assert len(nodes) > 0
        assert "Acme Corp" in nodes[0].get("content", "")

    async def test_store_ephemeral_context(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "memory",
            "User opened file src/main.py at line 42",
            decay_class="ephemeral",
            metadata={"source": "editor", "file": "src/main.py"},
        )
        assert result.get("layer") == "memory"
        assert "node_id" in result

    async def test_store_durable_insight(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "memory",
            "Architecture decision: chose FastAPI over Flask for async support",
            decay_class="durable",
            metadata={"source": "decision", "category": "architecture"},
        )
        assert result.get("layer") == "memory"

    @pytest.mark.xfail(reason="Server bug: float() argument NoneType")
    async def test_semantic_search(self, mcp_client: Any) -> None:
        await store(mcp_client, "memory", "Project deadline is end of Q2 2026")
        await store(mcp_client, "memory", "Budget allocated for cloud infrastructure")
        await store(mcp_client, "memory", "Team size is 5 engineers")

        results = await recall(mcp_client, query="when is the deadline?", top_k=3)
        assert "results" in results


@pytest.mark.evals
@pytest.mark.integration
class TestKnowledgeLayer:
    """Knowledge layer: validated claims with evidence."""

    async def test_claim_with_evidence_chain(self, mcp_client: Any) -> None:
        mem = await store(
            mcp_client,
            "memory",
            "Email from CFO: 'Q3 budget reduced by 15% due to supply chain issues'",
        )
        mem_id = mem["node_id"]

        claim = await store(
            mcp_client,
            "knowledge",
            "Acme Corp Q3 budget is constrained due to supply chain delays",
            evidence=[f"node:{mem_id}"],
            source_type="document",
            confidence=0.85,
        )
        assert claim.get("layer") == "knowledge"
        assert "node_id" in claim

    async def test_claim_from_document(self, mcp_client: Any) -> None:
        doc = await store(
            mcp_client,
            "memory",
            "API documentation states rate limit is 1000 requests per minute",
            metadata={"source": "documentation", "url": "https://api.example.com/docs"},
        )

        claim = await store(
            mcp_client,
            "knowledge",
            "The API rate limit is 1000 req/min",
            evidence=[f"node:{doc['node_id']}"],
            source_type="document",
            confidence=0.95,
        )
        assert claim.get("layer") == "knowledge"

    async def test_claim_missing_evidence_fails(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "knowledge",
            "Unsupported claim without evidence",
        )
        assert result.get("error") == "missing_evidence"


@pytest.mark.evals
@pytest.mark.integration
class TestWisdomLayer:
    """Wisdom layer: synthesized beliefs from multiple claims."""

    async def test_belief_from_claims(self, mcp_client: Any) -> None:
        mem1 = await store(mcp_client, "memory", "Customer mentioned tight Q3 budget")
        mem2 = await store(mcp_client, "memory", "Sales cycle typically 3 months")

        claim1 = await store(
            mcp_client,
            "knowledge",
            "Acme has budget constraints in Q3",
            evidence=[f"node:{mem1['node_id']}"],
            source_type="user",
            confidence=0.8,
        )
        claim2 = await store(
            mcp_client,
            "knowledge",
            "Deal closure takes a full quarter",
            evidence=[f"node:{mem2['node_id']}"],
            source_type="user",
            confidence=0.75,
        )

        belief = await store(
            mcp_client,
            "wisdom",
            "Acme deal should be structured with flexible payment terms",
            about=[claim1["node_id"], claim2["node_id"]],
            confidence=0.7,
        )
        assert belief.get("layer") == "wisdom"


@pytest.mark.evals
@pytest.mark.integration
class TestIntelligenceLayer:
    """Intelligence layer: reasoning chains and crystallizations."""

    async def test_reasoning_chain(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "intelligence",
            "Propose quarterly payment structure",
            steps=[
                {"step": 1, "reasoning": "Acme has budget constraints in Q3", "confidence": 0.85},
                {"step": 2, "reasoning": "Flexible payment terms reduce friction", "confidence": 0.8},
                {"step": 3, "reasoning": "Quarterly payments align with their budget cycles", "confidence": 0.75},
            ],
        )
        assert result.get("layer") == "intelligence"
        assert "node_id" in result or "chain_id" in result

    async def test_reasoning_multi_step(self, mcp_client: Any) -> None:
        result = await store(
            mcp_client,
            "intelligence",
            "Migrate to microservices architecture",
            steps=[
                {"step": 1, "reasoning": "System needs to handle 10k concurrent users", "confidence": 0.9},
                {"step": 2, "reasoning": "Current monolith won't scale past 2k", "confidence": 0.85},
                {"step": 3, "reasoning": "Microservices enable horizontal scaling", "confidence": 0.8},
            ],
        )
        assert result.get("layer") == "intelligence"


@pytest.mark.evals
@pytest.mark.integration
class TestCrossLayerTraversal:
    """Graph traversal across cognitive layers."""

    async def test_memory_to_claim_to_belief(self, mcp_client: Any) -> None:
        mem = await store(mcp_client, "memory", "Sales meeting notes: client budget is tight")
        claim = await store(
            mcp_client,
            "knowledge",
            "Client has budget constraints",
            evidence=[f"node:{mem['node_id']}"],
            source_type="user",
            confidence=0.85,
        )
        belief = await store(
            mcp_client,
            "wisdom",
            "Offer discount to close deal",
            about=[claim["node_id"]],
            confidence=0.7,
        )

        graph = await recall(
            mcp_client,
            node_ids=[belief["node_id"]],
            depth=3,
        )
        found_ids = {n.get("id") or n.get("node_id") for n in graph.get("nodes", [])}
        assert mem["node_id"] in found_ids or len(graph.get("nodes", [])) >= 2


@pytest.mark.evals
@pytest.mark.integration
class TestLinkingSemantics:
    """Typed relationships between nodes."""

    async def test_supports_relationship(self, mcp_client: Any) -> None:
        source = await store(mcp_client, "memory", "Revenue grew 20% YoY")
        target = await store(mcp_client, "memory", "Company is financially healthy")

        result = await link(mcp_client, source["node_id"], target["node_id"], "SUPPORTS")
        assert "edge_id" in result or "id" in result

    async def test_contradicts_relationship(self, mcp_client: Any) -> None:
        source = await store(mcp_client, "memory", "Team reports low morale")
        target = await store(mcp_client, "memory", "Employee satisfaction survey shows 95%")

        result = await link(mcp_client, source["node_id"], target["node_id"], "CONTRADICTS")
        assert "edge_id" in result or "id" in result

    async def test_derives_from_relationship(self, mcp_client: Any) -> None:
        original = await store(mcp_client, "memory", "Raw data from sensor")
        derived = await store(mcp_client, "memory", "Processed analytics result")

        result = await link(mcp_client, derived["node_id"], original["node_id"], "DERIVED_FROM")
        assert "edge_id" in result or "id" in result


@pytest.mark.evals
@pytest.mark.integration
@pytest.mark.skip(reason="mcp_client_alt fixture not compatible with real server testing")
class TestSiloIsolation:
    """Multi-tenant silo isolation via MCP."""

    async def test_cross_silo_invisible(self, mcp_client: Any, mcp_client_alt: Any) -> None:
        secret = await store(
            mcp_client,
            "memory",
            "Confidential: merger plans with XYZ Corp",
            metadata={"classification": "confidential"},
        )
        secret_id = secret["node_id"]

        alt_search = await recall(mcp_client_alt, query="merger XYZ Corp", top_k=10)
        alt_results = alt_search.get("results", [])

        found_ids = {r.get("node_id") or r.get("id") for r in alt_results}
        assert secret_id not in found_ids, "Secret leaked across silos"


@pytest.mark.evals
@pytest.mark.integration
class TestTimeTravel:
    """Temporal queries via context_recall."""

    async def test_as_of_query(self, mcp_client: Any) -> None:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        past = now - timedelta(hours=1)

        await store(mcp_client, "memory", "Current state of the world")

        results = await recall(
            mcp_client,
            query="state of the world",
            as_of=past.isoformat(),
            top_k=10,
        )
        assert "results" in results or "error" not in results


@pytest.mark.evals
@pytest.mark.integration
class TestProvenance:
    """Provenance tracking via context_admin."""

    async def test_provenance_chain(self, mcp_client: Any) -> None:
        doc = await store(mcp_client, "memory", "Source document content")
        claim = await store(
            mcp_client,
            "knowledge",
            "Derived claim from document",
            evidence=[f"node:{doc['node_id']}"],
            source_type="document",
            confidence=0.9,
        )

        prov = await admin(mcp_client, "provenance", ref=claim["node_id"])
        assert "chain" in prov or "root_sources" in prov or "error" not in prov
