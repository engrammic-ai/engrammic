"""Session compaction: convert completed ReasoningChain nodes to Memory-layer Event traces.

Compaction is a one-way operation: once a chain is compacted its steps are
summarised into an :Event node and the chain is tombstoned (compacted=true).
The original :ReasoningChain is preserved so the :DERIVED_FROM edge remains
traversable for provenance queries.

Public API
----------
compact_reasoning_chain(store, chain_id, silo_id, outcome) -> str
    Compact a single chain. Returns the new Event id.

batch_compact_chains(store, silo_id, statuses, limit) -> list[str]
    Find and compact up to *limit* compactable chains in a silo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.db.queries import (
    CREATE_REASONING_TRACE_EVENT,
    GET_COMPACTABLE_CHAINS,
    GET_REASONING_CHAIN_FOR_COMPACTION,
    TOMBSTONE_REASONING_CHAIN,
)
from context_service.engine.summarization import inline_summary, summarize_reasoning_steps

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

OutcomeT = Literal["committed", "abandoned", "expired"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_event_id(chain_id: str, silo_id: str) -> str:
    return hashlib.blake2b(
        f"reasoning_trace:{silo_id}:{chain_id}".encode(), digest_size=32
    ).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compact_reasoning_chain(
    store: HyperGraphStore,
    chain_id: str,
    silo_id: str,
    outcome: OutcomeT,
) -> str:
    """Compact a single ReasoningChain into a Memory-layer Event node.

    Steps:
    1. Fetch chain metadata from Memgraph.
    2. Summarise the steps (inline if <= 5, elided header/footer otherwise).
    3. Create :Event node with event_type="reasoning_trace".
    4. Create :DERIVED_FROM edge to original chain.
    5. Tombstone the chain (compacted=true).

    Parameters
    ----------
    store:
        A HyperGraphStore implementation (real or fake).
    chain_id:
        ID of the :ReasoningChain to compact.
    silo_id:
        Silo that owns the chain.
    outcome:
        One of "committed", "abandoned", or "expired".

    Returns
    -------
    str
        The id of the newly created :Event node.

    Raises
    ------
    ValueError
        If the chain is not found, is already compacted, or has a cold-form
        without compact_summary and without steps.
    """
    rows = await store.execute_query(
        GET_REASONING_CHAIN_FOR_COMPACTION,
        {"chain_id": chain_id, "silo_id": silo_id},
    )
    if not rows:
        raise ValueError(f"ReasoningChain {chain_id!r} not found in silo {silo_id!r}")

    chain = rows[0]

    if chain.get("compacted"):
        raise ValueError(f"ReasoningChain {chain_id!r} is already compacted")

    raw_steps: list[dict[str, Any]] | None = chain.get("steps")
    compact_summary: str | None = chain.get("compact_summary")
    agent_id: str = chain.get("agent_id") or ""

    summarization_pending = False
    if raw_steps:
        # Hot form: steps is a list of dicts (serialised from ChainStep)
        # Memgraph may return steps as a JSON string rather than a list.
        steps = raw_steps if isinstance(raw_steps, list) else json.loads(raw_steps)
        try:
            from context_service.config.settings import get_settings
            from context_service.llm import build_llm_provider

            settings = get_settings()
            model_spec = settings.models.get_model("summarization")
            llm_client = build_llm_provider(model_spec.provider, model_spec.model)
            content = await summarize_reasoning_steps(steps, llm_client=llm_client)
            summarization_pending = False
        except Exception as exc:
            logger.warning("summarization_failed", chain_id=chain_id, error=str(exc))
            content = inline_summary(steps)
            summarization_pending = True
        step_count = len(steps)
    elif compact_summary:
        # Cold form: already has a summary stored
        content = compact_summary
        step_count = 0
    else:
        raise ValueError(f"ReasoningChain {chain_id!r} has neither steps nor compact_summary")

    now = datetime.now(UTC)
    event_id = _make_event_id(chain_id, silo_id)

    async with store.transaction():
        await store.execute_write(
            CREATE_REASONING_TRACE_EVENT,
            {
                "event_id": event_id,
                "chain_id": chain_id,
                "silo_id": silo_id,
                "agent_id": agent_id,
                "content": content,
                "created_at": now.isoformat(),
                "step_count": step_count,
                "outcome": outcome,
                "summarization_pending": summarization_pending,
            },
        )

        await store.execute_write(
            TOMBSTONE_REASONING_CHAIN,
            {
                "chain_id": chain_id,
                "silo_id": silo_id,
                "event_id": event_id,
                "compacted_at": now.isoformat(),
            },
        )

    logger.info(
        "chain_compacted",
        chain_id=chain_id,
        silo_id=silo_id,
        event_id=event_id,
        step_count=step_count,
        outcome=outcome,
    )
    return event_id


async def batch_compact_chains(
    store: HyperGraphStore,
    silo_id: str,
    *,
    statuses: list[str] | None = None,
    limit: int = 50,
) -> list[str]:
    """Find and compact up to *limit* compactable chains in a silo.

    A chain is considered compactable if it has ``compacted != true`` and its
    status is in *statuses* (defaults to ``["published", "retracted"]``).

    Returns a list of newly created Event ids.
    """
    resolved_statuses = statuses if statuses is not None else ["published", "retracted"]

    chain_rows = await store.execute_query(
        GET_COMPACTABLE_CHAINS,
        {"silo_id": silo_id, "statuses": resolved_statuses, "limit": limit},
    )

    async def _compact_one(row: dict[str, Any]) -> str | None:
        chain_id = row["id"]
        outcome: OutcomeT = "committed" if row.get("status") == "published" else "expired"
        try:
            return await compact_reasoning_chain(store, chain_id, silo_id, outcome)
        except ValueError as exc:
            logger.warning("batch_compact_skip", chain_id=chain_id, reason=str(exc))
            return None

    results = await asyncio.gather(*[_compact_one(row) for row in chain_rows])
    event_ids = [r for r in results if isinstance(r, str)]

    return event_ids
