"""Consensus promotion to Finding."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from context_service.engine.queries import CREATE_FINDING_FROM_COMMITMENT, CREATE_PROMOTED_FROM_EDGE

if TYPE_CHECKING:
    from context_service.stores.memgraph import MemgraphClient


async def promote_consensus_to_finding(
    *,
    memgraph: MemgraphClient,
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

        for chain_id in contributing_chain_ids:
            await tx.run(
                CREATE_PROMOTED_FROM_EDGE,
                finding_id=finding_id,
                chain_id=chain_id,
            )

    return finding_id


__all__ = ["promote_consensus_to_finding"]
