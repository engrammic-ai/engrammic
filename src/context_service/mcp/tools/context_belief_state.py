"""MCP tool: context_belief_state - Query session WorkingBeliefs with contradiction detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_belief_state(
    session_id: str,
    silo_id: str,
    about: list[str] | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    store = get_context_service().graph_store

    rows = await store.execute_query(
        q.GET_WORKING_BELIEFS_FOR_SESSION,
        {"session_id": session_id, "silo_id": silo_id},
    )

    beliefs: list[dict[str, Any]] = []
    for row in rows:
        belief: dict[str, Any] = {
            "belief_id": row["belief_id"],
            "content": row["content"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "about_ids": row.get("about_ids") or [],
        }
        beliefs.append(belief)

    if about:
        about_set = set(about)
        beliefs = [b for b in beliefs if about_set.intersection(b["about_ids"])]

    contradiction_rows = await store.execute_query(
        q.DETECT_CONTRADICTIONS_IN_SESSION,
        {"session_id": session_id, "silo_id": silo_id},
    )

    contradictions = [
        {"belief_a": row["belief_a"], "belief_b": row["belief_b"]}
        for row in contradiction_rows
    ]

    return {
        "working_beliefs": beliefs,
        "potential_contradictions": contradictions,
        "reflection_suggested": len(contradictions) > 0,
        "session_id": session_id,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_belief_state tool."""

    @mcp.tool(
        name="context_belief_state",
        description=(
            "Query the session's active WorkingBeliefs with pairwise contradiction detection. "
            "Returns beliefs, potential contradictions, and a reflection_suggested flag. "
            "Filter by about to restrict to beliefs concerning specific nodes."
        ),
    )
    async def context_belief_state(
        session_id: str,
        about: list[str] | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Return working beliefs for a reasoning session.

        Args:
            session_id: ID of the ReasoningSession to query.
            about: Optional list of node IDs. When provided, only beliefs that
                reference at least one of these nodes are returned.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {working_beliefs, potential_contradictions, reflection_suggested, session_id}
            where each belief has {belief_id, content, confidence, created_at,
            updated_at, about_ids} and each contradiction is {belief_a, belief_b}.
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_belief_state(
            session_id=session_id,
            silo_id=resolved_silo_id,
            about=about,
        )
