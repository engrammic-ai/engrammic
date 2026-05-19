#!/usr/bin/env python3
"""Backfill tail_id/head_id pointers for existing supersession chains.

Usage:
    uv run python scripts/backfill_chain_pointers.py --silo-id <silo> [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_service.config.logging import get_logger
from context_service.stores.memgraph import MemgraphClient

logger = get_logger(__name__)

# Find all chain tails (nodes that are superseded but don't supersede anything)
FIND_CHAIN_TAILS = """
MATCH (tail)<-[:SUPERSEDES]-(successor)
WHERE tail.silo_id = $silo_id
  AND NOT (tail)-[:SUPERSEDES]->()
  AND tail.head_id IS NULL
RETURN DISTINCT tail.id AS tail_id
LIMIT $batch_size
"""

# For a given tail, walk chain to find head and set pointers.
# Verifies all nodes in chain belong to the same silo.
BACKFILL_CHAIN = """
MATCH (tail) WHERE tail.id = $tail_id AND tail.silo_id = $silo_id
// Walk chain to find head (node with no incoming SUPERSEDES)
MATCH path = (head)-[:SUPERSEDES*0..]->(tail)
WHERE NOT ()-[:SUPERSEDES]->(head) AND head.silo_id = $silo_id
  AND all(n IN nodes(path) WHERE n.silo_id = $silo_id)
WITH tail, head, nodes(path) AS chain_nodes
// Set tail's head_id
SET tail.head_id = head.id
// Set tail_id on all nodes in chain except tail itself
WITH tail, head, chain_nodes
UNWIND chain_nodes AS node
WITH tail, head, node WHERE node.id <> tail.id
SET node.tail_id = tail.id
RETURN head.id AS head_id, count(*) AS nodes_updated
"""


async def backfill_silo(client: MemgraphClient, silo_id: str, dry_run: bool) -> int:
    """Backfill pointers for all chains in a silo."""
    total_chains = 0
    batch_size = 100

    while True:
        tails = await client.execute_query(
            FIND_CHAIN_TAILS, {"silo_id": silo_id, "batch_size": batch_size}
        )
        if not tails:
            break

        for row in tails:
            tail_id = row["tail_id"]
            if dry_run:
                logger.info(f"[dry-run] Would backfill chain with tail {tail_id}")
            else:
                result = await client.execute_write(
                    BACKFILL_CHAIN, {"tail_id": tail_id, "silo_id": silo_id}
                )
                if result:
                    head_id = result[0].get("head_id")
                    nodes = result[0].get("nodes_updated", 0)
                    logger.info(f"Backfilled chain: tail={tail_id} head={head_id} nodes={nodes}")
            total_chains += 1

    return total_chains


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill supersession chain pointers")
    parser.add_argument("--silo-id", required=True, help="Silo ID to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done")
    args = parser.parse_args()

    from context_service.config.settings import get_settings

    settings = get_settings()
    client = MemgraphClient(settings.memgraph_uri)

    try:
        total = await backfill_silo(client, args.silo_id, args.dry_run)
        logger.info(f"Backfill complete: {total} chains processed")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
