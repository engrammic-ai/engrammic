"""Custodian task type dispatch table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.custodian.consolidation import ConclusionConsolidator
from context_service.custodian.handlers.consensus import handle_consensus_task
from context_service.custodian.task_types import CONSENSUS_ON_CHAINS, CustodianTaskType

if TYPE_CHECKING:
    from context_service.custodian.consolidation import ConclusionStore
    from context_service.stores.redis import RedisClient

log = get_logger(__name__)

TASK_HANDLERS = {
    CONSENSUS_ON_CHAINS: handle_consensus_task,
}

STITCH_TOOLS = [
    "read_reasoning_chains",
    "read_commitments_in_cluster",
]

# Run repair_orphaned_consolidations every this many dispatch calls.
_ORPHAN_REPAIR_INTERVAL = 50

# Redis key for the per-silo dispatch visit counter used to schedule orphan repair.
_DISPATCH_COUNTER_KEY = "custodian:dispatch_count:{silo_id}"


def validate_stitch_tools() -> None:
    """Validate STITCH_TOOLS entries exist in chain_reader module.

    Call at startup or in tests to catch tool name drift.
    """
    from context_service.custodian import chain_reader

    for tool_name in STITCH_TOOLS:
        if not hasattr(chain_reader, tool_name):
            raise ValueError(f"STITCH_TOOLS references missing function: {tool_name}")


async def dispatch_task(task_type: CustodianTaskType, **kwargs: Any) -> dict[str, Any]:
    handler = TASK_HANDLERS.get(task_type)
    if handler is None:
        raise NotImplementedError(f"No handler for task type: {task_type.name}")
    result = await handler(**kwargs)
    return dict(result)


async def dispatch_task_with_consolidation(
    task_type: CustodianTaskType,
    *,
    memgraph: ConclusionStore,
    redis_client: RedisClient,
    silo_id: str,
    query_context_hash: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch a custodian task and run a consolidation post-pass.

    After the primary task handler returns, this function:

    1. Calls ``ConclusionConsolidator.consolidate_by_hash`` for the given
       ``query_context_hash`` (when provided) to merge any newly created or
       updated :Conclusion nodes that share the same context hash.

    2. Periodically calls ``repair_orphaned_consolidations`` to recover from
       crashes where a canonical conclusion was written but the
       mark-consolidated step was interrupted.  The repair runs every
       ``_ORPHAN_REPAIR_INTERVAL`` dispatch calls, tracked per silo in Redis.

    The consolidation steps are best-effort: failures are logged but never
    propagate to the caller.  The primary task result is always returned.

    Args:
        task_type: The custodian task variant to dispatch.
        memgraph: A store satisfying ``ConclusionStore`` (typically
            ``MemgraphStore``).
        redis_client: The service ``RedisClient`` whose underlying
            ``Redis`` connection is used for locking and counters.
        silo_id: Tenant silo identifier.
        query_context_hash: Hash of the query context that produced the
            conclusions to consolidate.  When ``None`` the consolidation
            step is skipped.
        **kwargs: Remaining keyword arguments forwarded verbatim to the
            primary task handler (e.g. ``memgraph``, ``commitment_id``).
    """
    result = await dispatch_task(task_type, **kwargs)

    consolidator = ConclusionConsolidator(memgraph, redis_client._redis)

    # --- Step 1: consolidate by hash ---
    if query_context_hash is not None:
        try:
            canonical_id = await consolidator.consolidate_by_hash(silo_id, query_context_hash)
            if canonical_id is not None:
                log.info(
                    "post_dispatch_consolidation_complete",
                    silo_id=silo_id,
                    query_context_hash=query_context_hash,
                    canonical_id=canonical_id,
                )
                result["consolidation_canonical_id"] = canonical_id
        except Exception:
            log.warning(
                "post_dispatch_consolidation_failed",
                silo_id=silo_id,
                query_context_hash=query_context_hash,
                exc_info=True,
            )

    # --- Step 2: periodic orphan repair ---
    try:
        counter_key = _DISPATCH_COUNTER_KEY.format(silo_id=silo_id)
        count = await redis_client._redis.incr(counter_key)
        if count % _ORPHAN_REPAIR_INTERVAL == 0:
            repaired = await consolidator.repair_orphaned_consolidations(silo_id)
            log.info(
                "post_dispatch_orphan_repair",
                silo_id=silo_id,
                dispatch_count=count,
                repaired=repaired,
            )
    except Exception:
        log.warning(
            "post_dispatch_orphan_repair_failed",
            silo_id=silo_id,
            exc_info=True,
        )

    return result


__all__ = [
    "STITCH_TOOLS",
    "TASK_HANDLERS",
    "CustodianTaskType",
    "dispatch_task",
    "dispatch_task_with_consolidation",
    "validate_stitch_tools",
]
