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

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

OutcomeT = Literal["committed", "abandoned", "expired"]

_INLINE_STEP_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _summarise_steps(steps: list[dict[str, Any]]) -> str:
    """Produce a human-readable summary of reasoning steps.

    For chains with <= _INLINE_STEP_THRESHOLD steps all conclusions are
    inlined verbatim.  For longer chains the first two and last two steps
    are shown with a count of elided steps in the middle.
    """
    if not steps:
        return "(no steps)"

    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))

    if len(sorted_steps) <= _INLINE_STEP_THRESHOLD:
        lines = [
            f"[{s.get('step_index', i)}] {s.get('operation', 'step')}: {s.get('conclusion', '')}"
            for i, s in enumerate(sorted_steps)
        ]
        return "; ".join(lines)

    head = sorted_steps[:2]
    tail = sorted_steps[-2:]
    elided = len(sorted_steps) - 4
    lines = [
        f"[{s.get('step_index', i)}] {s.get('operation', 'step')}: {s.get('conclusion', '')}"
        for i, s in enumerate(head)
    ]
    lines.append(f"... ({elided} steps elided) ...")
    lines.extend(
        f"[{s.get('step_index', i + 2 + elided)}] {s.get('operation', 'step')}: {s.get('conclusion', '')}"
        for i, s in enumerate(tail)
    )
    return "; ".join(lines)


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

    if raw_steps:
        # Hot form: steps is a list of dicts (serialised from ChainStep)
        # Memgraph may return steps as a JSON string rather than a list.
        steps = raw_steps if isinstance(raw_steps, list) else json.loads(raw_steps)
        content = _summarise_steps(steps)
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

    event_ids: list[str] = []
    for row in chain_rows:
        chain_id = row["id"]
        # Default outcome for batch compaction: published -> committed, else expired
        outcome: OutcomeT = "committed" if row.get("status") == "published" else "expired"
        try:
            eid = await compact_reasoning_chain(store, chain_id, silo_id, outcome)
            event_ids.append(eid)
        except ValueError as exc:
            logger.warning("batch_compact_skip", chain_id=chain_id, reason=str(exc))

    return event_ids
