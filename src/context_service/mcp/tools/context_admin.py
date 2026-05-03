"""MCP tool: context_admin - Admin and utility actions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from context_service.config.settings import get_settings
from context_service.db.queries import (
    CREATE_CHAIN_REFERENCES_EDGE,
    GET_CHAIN_FOR_CLOSE,
    SET_CHAIN_SESSION_STATE,
)
from context_service.engine.compaction import compact_reasoning_chain
from context_service.engine.summarization import inline_summary, summarize_reasoning_steps
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_silo_service,
)
from context_service.mcp.tools.context_graph import _context_graph
from context_service.mcp.tools.context_history import _context_history
from context_service.services.models import derive_silo_id
from context_service.services.silo import ensure_silo, validate_silo_ownership

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from context_service.engine.protocols import HyperGraphStore

_VALID_ACTIONS = ("silo_list", "close_session", "provenance", "history")


async def _silo_list_impl() -> dict[str, Any]:
    """Internal implementation for silo_list (testable)."""
    auth = await get_mcp_auth_context()
    silo_svc = get_silo_service()

    silo = await ensure_silo(silo_svc, org_id=auth.org_id)

    return {
        "silos": [
            {
                "silo_id": str(silo.id),
                "name": silo.name,
                "org_id": silo.org_id,
                "description": silo.description,
                "dissolvability": silo.dissolvability,
            }
        ],
    }


async def close_reasoning_chain(
    store: HyperGraphStore,
    chain_id: str,
    silo_id: str,
    referenced_chain_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Core session-close logic -- fully unit-testable with a FakeGraphStore.

    Parameters
    ----------
    store:
        HyperGraphStore implementation (real or fake).
    chain_id:
        ID of the ReasoningChain to close.
    silo_id:
        Resolved silo ID (already validated against org).
    referenced_chain_ids:
        Optional list of chain IDs to link via REFERENCES edges.

    Returns
    -------
    dict
        Response payload suitable for direct return from the MCP tool.
    """
    settings = get_settings()
    now = datetime.now(UTC).isoformat()

    MAX_REFERENCES = 50
    if referenced_chain_ids and len(referenced_chain_ids) > MAX_REFERENCES:
        referenced_chain_ids = referenced_chain_ids[:MAX_REFERENCES]

    rows = await store.execute_query(
        GET_CHAIN_FOR_CLOSE,
        {"chain_id": chain_id, "silo_id": silo_id},
    )
    if not rows:
        return {
            "error": "chain_not_found",
            "message": f"ReasoningChain {chain_id!r} not found in silo {silo_id!r}",
        }

    chain = rows[0]

    if chain.get("session_state") == "closed":
        return {
            "error": "already_closed",
            "message": f"ReasoningChain {chain_id!r} is already closed",
        }

    await store.execute_write(
        SET_CHAIN_SESSION_STATE,
        {
            "chain_id": chain_id,
            "silo_id": silo_id,
            "session_state": "closed",
            "updated_at": now,
        },
    )

    refs_created: list[str] = []
    for ref_chain_id in referenced_chain_ids or []:
        ref_rows = await store.execute_write(
            CREATE_CHAIN_REFERENCES_EDGE,
            {
                "from_chain_id": chain_id,
                "to_chain_id": ref_chain_id,
                "silo_id": silo_id,
                "created_at": now,
                "reason": "session_reference",
            },
        )
        if ref_rows:
            refs_created.append(ref_chain_id)

    threshold = settings.compaction_step_threshold

    raw_steps = chain.get("steps")
    step_count: int
    summary: str | None = None
    event_id: str | None = None

    if raw_steps is not None:
        steps_list = raw_steps if isinstance(raw_steps, list) else json.loads(raw_steps)
        step_count = len(steps_list)
    else:
        steps_list = []
        step_count = 0

    summarization_triggered = step_count > threshold

    if summarization_triggered and not chain.get("compacted"):
        try:
            event_id = await compact_reasoning_chain(store, chain_id, silo_id, outcome="committed")
            await store.execute_write(
                SET_CHAIN_SESSION_STATE,
                {
                    "chain_id": chain_id,
                    "silo_id": silo_id,
                    "session_state": "summarized",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            if steps_list:
                try:
                    from context_service.llm import build_llm_provider

                    _llm_client = build_llm_provider(
                        settings.summarization_provider, settings.summarization_model
                    )
                except Exception:
                    _llm_client = None
                try:
                    summary = await summarize_reasoning_steps(steps_list, llm_client=_llm_client)
                except Exception:
                    summary = inline_summary(steps_list)
        except ValueError as exc:
            return {
                "error": "compaction_failed",
                "message": str(exc),
            }
    elif steps_list:
        summary = inline_summary(steps_list)
    elif chain.get("compact_summary"):
        summary = chain["compact_summary"]

    result: dict[str, Any] = {
        "chain_id": chain_id,
        "session_state": "summarized" if summarization_triggered else "closed",
        "summarization_triggered": summarization_triggered,
        "step_count": step_count,
        "closed_at": now,
    }
    if summary is not None:
        result["summary"] = summary
    if event_id is not None:
        result["event_id"] = event_id
    if refs_created:
        result["references_created"] = refs_created

    return result


async def _context_close_reasoning(
    silo_id: str,
    chain_id: str,
    referenced_chain_ids: list[str] | None = None,
) -> dict[str, Any]:
    """MCP-layer wrapper: auth check + feature gate, then delegates to core logic."""
    settings = get_settings()
    if not settings.session_compaction_enabled:
        return {
            "error": "feature_disabled",
            "message": "session_compaction_enabled is false; enable it to use context_close_reasoning",
        }

    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = str(derive_silo_id(auth.org_id))
    store = get_context_service().graph_store

    result = await close_reasoning_chain(
        store=store,
        chain_id=chain_id,
        silo_id=expected_silo_id,
        referenced_chain_ids=referenced_chain_ids,
    )
    if "error" not in result:
        result["silo_id"] = expected_silo_id
    return result


async def _context_admin(
    action: str,
    silo_id: str,
    ref: str | None = None,
    name: str | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if action == "silo_list":
        return await _silo_list_impl()

    if action == "close_session":
        if not ref:
            return {"error": "missing_ref", "message": "ref (chain_id) required for close_session"}
        return await _context_close_reasoning(silo_id=silo_id, chain_id=ref)

    if action == "provenance":
        if not ref:
            return {"error": "missing_ref", "message": "ref (node_id) required for provenance"}
        return await _context_graph(silo_id=silo_id, seed_nodes=[ref], mode="provenance")

    if action == "history":
        if not ref:
            return {
                "error": "missing_ref",
                "message": "ref (node_id or subject) required for history",
            }
        return await _context_history(silo_id=silo_id, node_id=ref)

    return {"error": "unknown_action", "valid": list(_VALID_ACTIONS)}


def register(mcp: FastMCP) -> None:
    """Register the context_admin tool."""

    @mcp.tool(
        name="context_admin",
        description=(
            "Admin and utility actions: silo_list, close_session, provenance, history. "
            "silo_list: list org silos. "
            "close_session: close a reasoning chain (ref=chain_id). "
            "provenance: trace citation chain for a node (ref=node_id). "
            "history: show belief evolution for a node (ref=node_id or subject)."
        ),
    )
    async def context_admin(
        action: Literal["silo_list", "close_session", "provenance", "history"],
        ref: str | None = None,
        name: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Admin and utility actions.

        Args:
            action: silo_list|close_session|provenance|history.
            ref: Node ID for provenance/history, chain_id for close_session.
            name: Reserved for future use.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            Action-specific response dict.
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_admin(
            action=action,
            silo_id=resolved_silo_id,
            ref=ref,
            name=name,
        )
