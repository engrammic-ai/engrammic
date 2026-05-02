"""Consensus promotion to Finding."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from context_service.engine.queries import (
    BATCH_CREATE_PROMOTED_FROM_EDGES,
    CREATE_FINDING_FROM_COMMITMENT,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


async def promote_consensus_to_finding(
    *,
    memgraph: HyperGraphStore,
    commitment_id: str,
    contributing_chain_ids: list[str],
    silo_id: str,
) -> str:
    """Promote a commitment with consensus chains to a Finding.

    Creates :Finding node with PROMOTED_FROM edges to all contributing chains.
    Sets chains to status='superseded'.

    The Finding ID is deterministic: same commitment + same contributing chains
    always produces the same ID, allowing MERGE to be idempotent on retry.
    All writes execute in a single transaction so partial promotion is impossible.
    """
    finding_id = hashlib.blake2b(
        f"finding:{commitment_id}:{','.join(sorted(contributing_chain_ids))}".encode(),
        digest_size=16,
    ).hexdigest()

    async with memgraph.transaction() as tx:
        result_cursor = await tx.run(
            CREATE_FINDING_FROM_COMMITMENT,
            commitment_id=commitment_id,
            silo_id=silo_id,
            finding_id=finding_id,
        )
        rows: list[dict[str, Any]] = await result_cursor.data()
        if not rows:
            raise ValueError(f"Failed to create finding for commitment {commitment_id}")

        # R-005: batch all PROMOTED_FROM edges in one UNWIND round-trip instead
        # of one tx.run() per chain.
        await tx.run(
            BATCH_CREATE_PROMOTED_FROM_EDGES,
            finding_id=finding_id,
            chain_ids=contributing_chain_ids,
        )

    return finding_id


__all__ = ["promote_consensus_to_finding"]
