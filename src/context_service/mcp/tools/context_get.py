# context_service/mcp/tools/context_get.py
"""MCP tool: context_get - Retrieve context nodes by ID."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from context_service.api.metrics import CONTEXT_GET_LATENCY
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_get(
    node_ids: str | list[str],
    silo_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Retrieve context nodes by ID.

    Args:
        node_ids: A single node ID string or a list of node ID strings.
        silo_id: UUID of the silo to scope the lookup. Defaults to the org's primary silo.
        as_of: Reserved for point-in-time retrieval. Currently raises
            "as_of_not_supported" if non-null -- time-travel querying is
            not wired yet (see meta-memory-roadmap.md).

    Returns:
        Dictionary with 'nodes' list containing node data.
    """
    if as_of is not None:
        return {
            "error": "as_of_not_supported",
            "message": "Point-in-time retrieval is not yet implemented",
        }

    _start = time.perf_counter()
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    if isinstance(node_ids, str):
        node_ids = [node_ids]

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err
        try:
            resolved_silo_id = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id", "silo_id": silo_id}
    else:
        resolved_silo_id = derive_silo_id(auth.org_id)

    nodes_out: list[dict[str, Any]] = []
    for nid in node_ids:
        try:
            node_uuid = uuid.UUID(nid)
        except ValueError:
            nodes_out.append({"error": "invalid_node_id", "node_id": nid})
            continue

        node = await ctx_svc.get(node_uuid, resolved_silo_id)
        if node is None:
            nodes_out.append(
                {
                    "error": "node_not_found",
                    "node_id": nid,
                    "message": "Node may have been deleted or the silo_id is wrong.",
                }
            )
        else:
            props = node.properties or {}
            nodes_out.append(
                {
                    "node_id": str(node.id),
                    "content": node.content,
                    "type": node.type,
                    "silo_id": str(node.silo_id) if node.silo_id else None,
                    "properties": props,
                    "source_uri": node.source_uri,
                    "content_hash": node.content_hash,
                    "layer": props.get("layer"),
                    "summary": props.get("summary"),
                    "confidence": props.get("confidence"),
                    "tags": props.get("tags"),
                    "created_at": (node.created_at.isoformat() if node.created_at else None),
                }
            )

    redis = get_redis()
    if redis is not None:
        emits = [
            emit_access_event(redis, str(resolved_silo_id), n["node_id"])
            for n in nodes_out
            if n.get("node_id") is not None
        ]
        if emits:
            await asyncio.gather(*emits)

    CONTEXT_GET_LATENCY.observe(time.perf_counter() - _start)
    return {"nodes": nodes_out}


def register(mcp: FastMCP) -> None:
    """Register the context_get tool on the MCP server."""

    @mcp.tool(
        name="context_get",
        description=(
            "Retrieve one or more context nodes by their IDs. "
            "Returns full node data including content, properties, and version."
        ),
    )
    async def context_get(
        node_ids: str | list[str],
        silo_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        return await _context_get(node_ids, silo_id, as_of)
