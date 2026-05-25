# src/context_service/mcp/tools/hypothesize.py
"""MCP tool: hypothesize - Form a tentative belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.context_store import _context_store_belief
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("hypothesize")
async def _hypothesize_impl(
    hypothesis: str,
    about: list[str],
    confidence: float = 0.8,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Implementation for hypothesize tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "hypothesize")
    silo_id = str(derive_silo_id(auth.org_id))

    resolved_session_id = session_id or auth.session_id
    if not resolved_session_id:
        return {
            "error": "no_session",
            "message": "No session available. Connect with a session-enabled auth.",
        }

    result = await _context_store_belief(
        silo_id=silo_id,
        content=hypothesis,
        session_id=resolved_session_id,
        about=about,
        confidence=confidence,
    )

    if "error" not in result:
        result["session_id"] = resolved_session_id

    return result


def register(mcp: FastMCP) -> None:
    """Register the hypothesize tool."""

    @mcp.tool(
        name="hypothesize",
        description=get_tool_description("hypothesize"),
    )
    @mcp_error_boundary
    async def hypothesize(
        hypothesis: str,
        about: list[str] | str,
        confidence: float = 0.8,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Form a tentative belief during reasoning.

        Args:
            hypothesis: Tentative belief.
            about: REQUIRED. Node IDs this concerns.
            confidence: 0.0-1.0 (default 0.8).
            session_id: Optional override. Defaults to MCP session.

        Returns:
            {belief_id, session_id, potential_conflicts, created_at}
        """
        start = time.perf_counter()
        success = True
        about_list = coerce_list(about)
        try:
            return await _hypothesize_impl(hypothesis, about_list, confidence, session_id)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("hypothesize", (time.perf_counter() - start) * 1000, success=success)
