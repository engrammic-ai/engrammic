# src/context_service/mcp/tools/patterns.py
"""MCP tool: patterns - Discover workflow templates."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.server import get_mcp_auth_context, get_skill_service
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _patterns_impl(
    action: Literal["list", "get", "search"],
    name: str | None = None,
    query: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Implementation for patterns tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))

    try:
        skill_svc = get_skill_service()
    except RuntimeError:
        return {"error": "patterns_unavailable", "message": "Patterns service not configured"}

    if action == "list":
        skills = await skill_svc.list(silo_id, namespace=profile, limit=50, offset=0)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }

    elif action == "get":
        if not name:
            return {"error": "missing_name", "message": "name required for get action"}
        skill = await skill_svc.get(silo_id, name)
        if not skill:
            return {"error": "not_found", "message": f"Pattern not found: {name}"}
        return {"pattern": skill.model_dump(exclude_none=True)}

    elif action == "search":
        if not query:
            return {"error": "missing_query", "message": "query required for search action"}
        skills = await skill_svc.search(silo_id, query, namespace=profile, limit=20)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }

    return {"error": "invalid_action", "valid": ["list", "get", "search"]}


def register(mcp: FastMCP) -> None:
    """Register the patterns tool."""

    @mcp.tool(
        name="patterns",
        description=get_tool_description("patterns"),
    )
    async def patterns(
        action: Literal["list", "get", "search"],
        name: str | None = None,
        query: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Discover workflow templates for common tasks.

        Args:
            action: list|get|search.
            name: Pattern name (for get).
            query: Search query (for search).
            profile: Filter by profile: standard|reasoning.

        Returns:
            {patterns: [...]} or {pattern: {...}}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _patterns_impl(action, name, query, profile)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("patterns", (time.perf_counter() - start) * 1000, success=success)
