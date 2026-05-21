# src/context_service/mcp/tools/patterns.py
"""MCP tool: patterns - Discover workflow templates."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, get_preset_resolver, get_skill_service
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("patterns")
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

    # When profile is omitted, resolve the silo's ICP preset namespace for ranking/qualification.
    # When profile is explicit, use it verbatim as the namespace filter (no preset lookup).
    preset_ns: str | None = None
    if profile is None:
        try:
            preset = await get_preset_resolver().resolve(silo_id)
            preset_ns = preset.namespace
        except RuntimeError:
            # Resolver not configured (startup) -> degrade gracefully to base, non-preset behavior.
            preset_ns = None

    def _rank(skills: list[Any]) -> list[Any]:
        """Reorder so preset-namespace skills appear first, rest follow in original order."""
        if preset_ns is None:
            return skills
        prefix = f"{preset_ns}:"
        first = [s for s in skills if s.name.startswith(prefix)]
        rest = [s for s in skills if not s.name.startswith(prefix)]
        return first + rest

    if action == "list":
        # Do NOT filter by namespace when using preset; rank instead so base skills remain visible.
        skills = await skill_svc.list(silo_id, namespace=profile, limit=50, offset=0)
        ranked = _rank(skills)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in ranked],
            "count": len(ranked),
        }

    elif action == "get":
        if not name:
            return {"error": "missing_name", "message": "name required for get action"}
        # Auto-qualify bare names (no ':') ONLY against the preset namespace; a bare name that
        # exists under a different namespace (e.g. engrammic:) returns not_found unless passed
        # fully qualified.
        resolved_name = name
        if ":" not in name and preset_ns is not None:
            resolved_name = f"{preset_ns}:{name}"
        skill = await skill_svc.get(silo_id, resolved_name)
        if not skill:
            return {"error": "not_found", "message": f"Pattern not found: {resolved_name}"}
        return {"pattern": skill.model_dump(exclude_none=True)}

    elif action == "search":
        # Do NOT filter by namespace when using preset; rank instead.
        if not query:
            return {"error": "missing_query", "message": "query required for search action"}
        skills = await skill_svc.search(silo_id, query, namespace=profile, limit=20)
        ranked = _rank(skills)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in ranked],
            "count": len(ranked),
        }

    return {"error": "invalid_action", "valid": ["list", "get", "search"]}


def register(mcp: FastMCP) -> None:
    """Register the patterns tool."""

    @mcp.tool(
        name="patterns",
        description=get_tool_description("patterns"),
    )
    @mcp_error_boundary
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
            profile: Filter by profile namespace (e.g. standard|reasoning). When omitted, the
                silo's ICP preset namespace is used to rank matching skills first and to
                auto-qualify a bare name (no colon) in a get action to that namespace.

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
