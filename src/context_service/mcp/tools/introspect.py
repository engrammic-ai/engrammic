# src/context_service/mcp/tools/introspect.py
"""MCP tool: introspect - Metacognitive queries about the knowledge graph."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_context_service, get_mcp_auth_context
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _introspect_impl(
    query_type: str,
    node_id: str | None = None,
    agent_id: str | None = None,
    min_threshold: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Implementation for introspect tool."""
    from context_service.engine.intelligence import (
        detect_volatile_topics,
        find_knowledge_gaps,
        get_agent_contribution_stats,
        get_belief_provenance,
    )

    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    ctx = get_context_service()
    store = ctx._memgraph

    if query_type == "volatility":
        min_chain = min_threshold or 3
        topics = await detect_volatile_topics(store, silo_id, min_chain, limit)
        return {
            "query_type": "volatility",
            "volatile_topics": topics,
            "count": len(topics),
        }

    elif query_type == "gaps":
        min_asks = min_threshold or 2
        gaps = await find_knowledge_gaps(store, silo_id, min_asks, limit)
        return {
            "query_type": "gaps",
            "knowledge_gaps": gaps,
            "count": len(gaps),
        }

    elif query_type == "provenance":
        if not node_id:
            return {"error": "missing_node_id", "message": "node_id required for provenance query"}
        provenance = await get_belief_provenance(store, silo_id, node_id)
        if not provenance:
            return {"error": "not_found", "message": f"Belief {node_id} not found"}
        return {
            "query_type": "provenance",
            **provenance,
        }

    elif query_type == "contributions":
        target_agent = agent_id or auth.agent_id
        if not target_agent:
            return {
                "error": "missing_agent_id",
                "message": "agent_id required for contributions query",
            }
        stats = await get_agent_contribution_stats(store, silo_id, target_agent)
        if not stats:
            return {"error": "not_found", "message": f"Agent {target_agent} not found"}
        return {
            "query_type": "contributions",
            **stats,
        }

    else:
        return {
            "error": "invalid_query_type",
            "valid_types": ["volatility", "gaps", "provenance", "contributions"],
        }


def register(mcp: FastMCP) -> None:
    """Register the introspect tool."""

    @mcp.tool(
        name="introspect",
        description=get_tool_description("introspect"),
    )
    @mcp_error_boundary
    async def introspect(
        query_type: str,
        node_id: str | None = None,
        agent_id: str | None = None,
        min_threshold: int | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Query metacognitive state of the knowledge graph.

        Args:
            query_type: One of: volatility, gaps, provenance, contributions
            node_id: Required for provenance query (belief node ID)
            agent_id: For contributions query (defaults to current agent)
            min_threshold: Minimum threshold (chain length for volatility, ask count for gaps)
            limit: Max results to return

        Returns:
            Query-specific results
        """
        return await _introspect_impl(query_type, node_id, agent_id, min_threshold, limit)
