# context_service/mcp/tools/context_get.py
"""MCP tool: context_get - Retrieve context nodes by ID."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from context_service.db.queries import GET_REFLECTIONS_FOR_NODE_BY_AGENT
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event
from context_service.telemetry.metrics import record_mcp_tool


async def _context_get(
    node_ids: str | list[str],
    silo_id: str | None = None,
    as_of: str | None = None,
    include_reflections: bool = False,
    reflections_agent_id: str | None = None,
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
        # Parse and normalize to UTC
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            as_of_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return {
                "error": "invalid_as_of_format",
                "message": "as_of must be an ISO 8601 datetime string (e.g. 2026-04-01T00:00:00Z)",
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

        # Parse node IDs
        node_uuids: list[uuid.UUID] = []
        invalid_ids: list[dict[str, Any]] = []
        for nid in node_ids:
            try:
                node_uuids.append(uuid.UUID(nid))
            except ValueError:
                invalid_ids.append({"error": "invalid_node_id", "node_id": nid})

        if not node_uuids:
            record_mcp_tool("context_get", (time.perf_counter() - _start) * 1000)
            return {"nodes": invalid_ids}

        temporal_results = await ctx_svc.get_temporal(node_uuids, resolved_silo_id, as_of_dt)

        record_mcp_tool("context_get", (time.perf_counter() - _start) * 1000)
        return {"nodes": invalid_ids + temporal_results}

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

    bad_ids: list[dict[str, Any]] = []
    valid_node_ids: list[str] = []
    for nid in node_ids:
        try:
            uuid.UUID(nid)
            valid_node_ids.append(nid)
        except ValueError:
            bad_ids.append({"error": "invalid_node_id", "node_id": nid})

    node_map = await ctx_svc._batch_fetch_nodes(valid_node_ids, resolved_silo_id)

    nodes_out: list[dict[str, Any]] = []
    for nid in valid_node_ids:
        node = node_map.get(nid)
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
            node_dict: dict[str, Any] = {
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
                "tier": props.get("tier"),
                **({"status": props["status"]} if props.get("status") is not None else {}),
            }
            nodes_out.append(node_dict)

    if include_reflections and nodes_out:
        reflection_tasks = [
            ctx_svc.graph_store.execute_query(
                GET_REFLECTIONS_FOR_NODE_BY_AGENT,
                {
                    "node_id": n["node_id"],
                    "silo_id": str(resolved_silo_id),
                    "agent_id": reflections_agent_id,
                },
            )
            for n in nodes_out
            if n.get("node_id") is not None
        ]
        reflection_results = await asyncio.gather(*reflection_tasks)
        idx = 0
        for n in nodes_out:
            if n.get("node_id") is not None:
                n["reflections"] = [dict(r) for r in reflection_results[idx]]
                idx += 1

    nodes_out = bad_ids + nodes_out

    redis = get_redis()
    if redis is not None:
        emits = [
            emit_access_event(redis, str(resolved_silo_id), n["node_id"])
            for n in nodes_out
            if n.get("node_id") is not None
        ]
        if emits:
            await asyncio.gather(*emits)

    record_mcp_tool("context_get", (time.perf_counter() - _start) * 1000)
    return {"nodes": nodes_out}
