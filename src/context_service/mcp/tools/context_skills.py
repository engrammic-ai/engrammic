"""MCP tool: context_skills - Read-only skill registry access for agents."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.mcp.server import get_mcp_auth_context
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from context_service.services.skills import SkillService

logger = structlog.get_logger(__name__)


async def _context_skills_impl(
    service: SkillService,
    silo_id: str,
    action: Literal["list", "get", "search"],
    name: str | None = None,
    query: str | None = None,
    namespace: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Internal implementation for testing."""

    if action == "list":
        skills = await service.list(silo_id, namespace=namespace, limit=limit, offset=offset)
        return {
            "skills": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }

    elif action == "get":
        if not name:
            return {"error": "name is required for get action"}
        skill = await service.get(silo_id, name)
        if not skill:
            return {"error": f"Skill not found: {name}"}
        return {"skill": skill.model_dump(exclude_none=True)}

    elif action == "search":
        if not query:
            return {"error": "query is required for search action"}
        skills = await service.search(silo_id, query, namespace=namespace, limit=limit)
        return {
            "skills": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }

    return {"error": f"Unknown action: {action}"}


def register(mcp: FastMCP, service: SkillService) -> None:
    """Register context_skills tool with FastMCP."""

    @mcp.tool()
    async def context_skills(
        action: Literal["list", "get", "search"],
        name: str | None = None,
        query: str | None = None,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read-only access to the skill registry.

        Actions:
        - list: List all skills (builtins + user skills)
        - get: Get a specific skill by name
        - search: Search skills by name/description

        Args:
            action: The operation to perform
            name: Skill name (required for get)
            query: Search query (required for search)
            namespace: Filter by namespace prefix
            limit: Max results (default 50, max 200)
            offset: Pagination offset
        """
        auth = await get_mcp_auth_context()
        silo_id = str(derive_silo_id(auth.org_id))

        limit = min(limit, 200)

        start = time.perf_counter()
        try:
            result = await _context_skills_impl(
                service=service,
                silo_id=silo_id,
                action=action,
                name=name,
                query=query,
                namespace=namespace,
                limit=limit,
                offset=offset,
            )
            record_mcp_tool("context_skills", (time.perf_counter() - start) * 1000, success=True)
            return result
        except Exception:
            record_mcp_tool("context_skills", (time.perf_counter() - start) * 1000, success=False)
            raise
