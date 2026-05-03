"""MCP tool: context_close_reasoning - Explicitly close a reasoning session.

Gated behind settings.session_compaction_enabled. When the feature flag is off
the tool returns a feature_disabled error so callers can handle gracefully.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.config.settings import get_settings
from context_service.db.queries import (
    CREATE_CHAIN_REFERENCES_EDGE,
    GET_CHAIN_FOR_CLOSE,
    SET_CHAIN_SESSION_STATE,
)
from context_service.engine.compaction import compact_reasoning_chain
from context_service.engine.summarization import inline_summary, summarize_reasoning_steps

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from context_service.engine.protocols import HyperGraphStore


async def close_reasoning_chain(
    store: HyperGraphStore,
    chain_id: str,
    silo_id: str,
    referenced_chain_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Core session-close logic — fully unit-testable with a FakeGraphStore.

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

    # Set session_state to closed
    await store.execute_write(
        SET_CHAIN_SESSION_STATE,
        {
            "chain_id": chain_id,
            "silo_id": silo_id,
            "session_state": "closed",
            "updated_at": now,
        },
    )

    # Create REFERENCES edges to any linked chains
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

    # Determine whether to compact (summarize)
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
            # Advance state to summarized
            await store.execute_write(
                SET_CHAIN_SESSION_STATE,
                {
                    "chain_id": chain_id,
                    "silo_id": silo_id,
                    "session_state": "summarized",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            # Build summary for the response
            if steps_list:
                try:
                    from context_service.llm import build_llm_provider

                    llm_client = build_llm_provider(
                        settings.summarization_provider, settings.summarization_model
                    )
                    summary = await summarize_reasoning_steps(steps_list, llm_client=llm_client)
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
    from context_service.mcp.server import (
        get_context_service,
        get_mcp_auth_context,
        get_silo_service,
    )
    from context_service.services.models import derive_silo_id
    from context_service.services.silo import validate_silo_ownership

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
    # Inject silo_id into result for callers (not exposed from core logic)
    if "error" not in result:
        result["silo_id"] = silo_id
    return result


def register(mcp: FastMCP) -> None:
    """Register the context_close_reasoning tool."""

    @mcp.tool(
        name="context_close_reasoning",
        description=(
            "Explicitly close a reasoning session (Intelligence layer). "
            "Sets the chain session_state to 'closed' and, if the chain exceeds "
            "compaction_step_threshold steps, triggers summarization and compaction. "
            "Optionally links this chain to related chains via REFERENCES edges. "
            "Requires session_compaction_enabled=true."
        ),
    )
    async def context_close_reasoning(
        silo_id: str,
        chain_id: str,
        referenced_chain_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Explicitly close a reasoning session.

        Args:
            silo_id: UUID of the silo.
            chain_id: ID of the ReasoningChain to close.
            referenced_chain_ids: Optional list of chain IDs this session references.
                Creates REFERENCES edges between chains for cross-session traversal.

        Returns:
            {chain_id, silo_id, session_state, summarization_triggered, step_count,
             closed_at, summary?, event_id?, references_created?}
        """
        return await _context_close_reasoning(
            silo_id=silo_id,
            chain_id=chain_id,
            referenced_chain_ids=referenced_chain_ids,
        )
