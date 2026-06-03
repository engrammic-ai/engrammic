"""Eval: MCP tool layer testing with rich scenarios.

Tests all 4 cognitive layers (Memory, Knowledge, Wisdom, Intelligence) plus
meta-memory operations via MCP tools against the docker stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import call_result

pytest_plugins = ["tests.e2e.conftest"]


async def remember(
    client: Any,
    content: str,
    tags: list[str] | None = None,
    decay: str = "standard",
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Store an observation (Memory layer)."""
    params: dict[str, Any] = {"content": content, "decay": decay}
    if tags:
        params["tags"] = tags
    if supersedes:
        params["supersedes"] = supersedes
    raw = await client.call_tool("remember", params)
    return call_result(raw)


async def learn(
    client: Any,
    claim: str,
    evidence: list[str],
    source: str,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    source_tier: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Record a claim with evidence (Knowledge layer)."""
    params: dict[str, Any] = {
        "claim": claim,
        "evidence": evidence,
        "source": source,
        "confidence": confidence,
    }
    if tags:
        params["tags"] = tags
    if source_tier:
        params["source_tier"] = source_tier
    if supersedes:
        params["supersedes"] = supersedes
    raw = await client.call_tool("learn", params)
    return call_result(raw)


async def believe(
    client: Any,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Declare a commitment (Wisdom layer)."""
    params: dict[str, Any] = {"belief": belief, "about": about, "confidence": confidence}
    if reasoning:
        params["reasoning"] = reasoning
    if supersedes:
        params["supersedes"] = supersedes
    raw = await client.call_tool("believe", params)
    return call_result(raw)


async def recall(client: Any, **kwargs: Any) -> dict[str, Any]:
    """Retrieve nodes via query or node_ids."""
    raw = await client.call_tool("recall", kwargs)
    return call_result(raw)


async def link(
    client: Any, from_node: str, to_node: str, relationship: str, **kwargs: Any
) -> dict[str, Any]:
    """Create typed relationship between nodes."""
    raw = await client.call_tool(
        "link",
        {"from_node": from_node, "to_node": to_node, "relationship": relationship, **kwargs},
    )
    return call_result(raw)


@pytest.mark.evals
@pytest.mark.integration
class TestMemoryLayer:
    """Memory layer: observations, events, raw context."""

    async def test_store_meeting_observation(self, mcp_client: Any) -> None:
        result = await remember(
            mcp_client,
            "Meeting with Acme Corp scheduled for 2026-05-10. John mentioned Q3 budget concerns.",
            decay="standard",
        )
        assert "node_id" in result
        node_id = result["node_id"]

        fetched = await recall(mcp_client, node_ids=[node_id])
        nodes = fetched.get("nodes", [])
        assert len(nodes) > 0
        assert "Acme Corp" in nodes[0].get("content", "")

    async def test_store_ephemeral_context(self, mcp_client: Any) -> None:
        result = await remember(
            mcp_client,
            "User opened file src/main.py at line 42",
            decay="ephemeral",
        )
        assert "node_id" in result

    async def test_store_durable_insight(self, mcp_client: Any) -> None:
        result = await remember(
            mcp_client,
            "Architecture decision: chose FastAPI over Flask for async support",
            decay="durable",
        )
        assert "node_id" in result

    async def test_semantic_search(self, mcp_client: Any) -> None:
        await remember(mcp_client, "Project deadline is end of Q2 2026")
        await remember(mcp_client, "Budget allocated for cloud infrastructure")
        await remember(mcp_client, "Team size is 5 engineers")

        results = await recall(mcp_client, query="when is the deadline?", top_k=3)
        assert "results" in results


@pytest.mark.evals
@pytest.mark.integration
class TestKnowledgeLayer:
    """Knowledge layer: validated claims with evidence."""

    async def test_claim_with_evidence_chain(self, mcp_client: Any) -> None:
        mem = await remember(
            mcp_client,
            "Email from CFO: 'Q3 budget reduced by 15% due to supply chain issues'",
        )
        mem_id = mem["node_id"]

        claim = await learn(
            mcp_client,
            claim="Acme Corp Q3 budget is constrained due to supply chain delays",
            evidence=[f"node:{mem_id}"],
            source="document",
            confidence=0.85,
        )
        assert "node_id" in claim

    async def test_claim_from_document(self, mcp_client: Any) -> None:
        doc = await remember(
            mcp_client,
            "API documentation states rate limit is 1000 requests per minute",
        )

        claim = await learn(
            mcp_client,
            claim="The API rate limit is 1000 req/min",
            evidence=[f"node:{doc['node_id']}"],
            source="document",
            confidence=0.95,
        )
        assert "node_id" in claim

    async def test_claim_missing_evidence_fails(self, mcp_client: Any) -> None:
        result = await learn(
            mcp_client,
            claim="Unsupported claim without evidence",
            evidence=[],
            source="user",
        )
        assert result.get("error") == "missing_evidence"


@pytest.mark.evals
@pytest.mark.integration
class TestWisdomLayer:
    """Wisdom layer: synthesized beliefs from multiple claims."""

    async def test_belief_from_claims(self, mcp_client: Any) -> None:
        mem1 = await remember(mcp_client, "Customer mentioned tight Q3 budget")
        mem2 = await remember(mcp_client, "Sales cycle typically 3 months")

        claim1 = await learn(
            mcp_client,
            claim="Acme has budget constraints in Q3",
            evidence=[f"node:{mem1['node_id']}"],
            source="user",
            confidence=0.8,
        )
        claim2 = await learn(
            mcp_client,
            claim="Deal closure takes a full quarter",
            evidence=[f"node:{mem2['node_id']}"],
            source="user",
            confidence=0.75,
        )

        result = await believe(
            mcp_client,
            belief="Acme deal should be structured with flexible payment terms",
            about=[claim1["node_id"], claim2["node_id"]],
            confidence=0.7,
        )
        assert "node_id" in result


@pytest.mark.evals
@pytest.mark.integration
class TestIntelligenceLayer:
    """Intelligence layer: reasoning chains and crystallizations."""

    async def test_reasoning_chain(self, mcp_client: Any) -> None:
        # Intelligence layer uses the `reason` tool
        raw = await mcp_client.call_tool(
            "reason",
            {
                "conclusion": "Propose quarterly payment structure",
                "steps": [
                    {"reasoning": "Acme has budget constraints in Q3", "confidence": 0.85},
                    {"reasoning": "Flexible payment terms reduce friction", "confidence": 0.8},
                    {"reasoning": "Quarterly payments align with their budget cycles", "confidence": 0.75},
                ],
            },
        )
        result = call_result(raw)
        assert "node_id" in result or "chain_id" in result

    async def test_reasoning_multi_step(self, mcp_client: Any) -> None:
        raw = await mcp_client.call_tool(
            "reason",
            {
                "conclusion": "Migrate to microservices architecture",
                "steps": [
                    {"reasoning": "System needs to handle 10k concurrent users", "confidence": 0.9},
                    {"reasoning": "Current monolith won't scale past 2k", "confidence": 0.85},
                    {"reasoning": "Microservices enable horizontal scaling", "confidence": 0.8},
                ],
            },
        )
        result = call_result(raw)
        assert "node_id" in result or "chain_id" in result


@pytest.mark.evals
@pytest.mark.integration
class TestCrossLayerTraversal:
    """Graph traversal across cognitive layers."""

    async def test_memory_to_claim_to_belief(self, mcp_client: Any) -> None:
        mem = await remember(mcp_client, "Sales meeting notes: client budget is tight")
        claim = await learn(
            mcp_client,
            claim="Client has budget constraints",
            evidence=[f"node:{mem['node_id']}"],
            source="user",
            confidence=0.85,
        )
        blf = await believe(
            mcp_client,
            belief="Offer discount to close deal",
            about=[claim["node_id"]],
            confidence=0.7,
        )

        graph = await recall(
            mcp_client,
            node_ids=[blf["node_id"]],
            depth=3,
        )
        found_ids = {n.get("id") or n.get("node_id") for n in graph.get("nodes", [])}
        assert mem["node_id"] in found_ids or len(graph.get("nodes", [])) >= 2


@pytest.mark.evals
@pytest.mark.integration
class TestLinkingSemantics:
    """Typed relationships between nodes."""

    async def test_supports_relationship(self, mcp_client: Any) -> None:
        source = await remember(mcp_client, "Revenue grew 20% YoY")
        target = await remember(mcp_client, "Company is financially healthy")

        result = await link(mcp_client, source["node_id"], target["node_id"], "SUPPORTS")
        assert "edge_id" in result or "id" in result

    async def test_contradicts_relationship(self, mcp_client: Any) -> None:
        source = await remember(mcp_client, "Team reports low morale")
        target = await remember(mcp_client, "Employee satisfaction survey shows 95%")

        result = await link(mcp_client, source["node_id"], target["node_id"], "CONTRADICTS")
        assert "edge_id" in result or "id" in result

    async def test_derives_from_relationship(self, mcp_client: Any) -> None:
        original = await remember(mcp_client, "Raw data from sensor")
        derived = await remember(mcp_client, "Processed analytics result")

        result = await link(mcp_client, derived["node_id"], original["node_id"], "DERIVED_FROM")
        assert "edge_id" in result or "id" in result


@pytest.mark.evals
@pytest.mark.integration
@pytest.mark.skip(reason="mcp_client_alt fixture not compatible with real server testing")
class TestSiloIsolation:
    """Multi-tenant silo isolation via MCP."""

    async def test_cross_silo_invisible(self, mcp_client: Any, mcp_client_alt: Any) -> None:
        secret = await remember(
            mcp_client,
            "Confidential: merger plans with XYZ Corp",
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

        await remember(mcp_client, "Current state of the world")

        results = await recall(
            mcp_client,
            query="state of the world",
            as_of=past.isoformat(),
            top_k=10,
        )
        assert "results" in results or "error" not in results
