"""Migrate legacy MetaObservation nodes to Memory{memory_type:"reflection"} in Memgraph.

Usage:
    uv run python -m scripts.migrate_meta_observations --all-silos
    uv run python -m scripts.migrate_meta_observations --silo-id <id>
    uv run python -m scripts.migrate_meta_observations --verify
    uv run python -m scripts.migrate_meta_observations --dry-run --all-silos

The migration is idempotent: already-migrated nodes (Memory label) are skipped.
MetaObservation label is removed and Memory label is set; memory_type="reflection"
is added so queries using the new schema find them correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver

_MIGRATE_SILO = """
MATCH (n:MetaObservation {silo_id: $silo_id})
WHERE NOT n:Memory
SET n:Memory
SET n.memory_type = 'reflection'
REMOVE n:MetaObservation
RETURN count(n) AS processed
"""

_DRY_RUN_SILO = """
MATCH (n:MetaObservation {silo_id: $silo_id})
WHERE NOT n:Memory
RETURN count(n) AS would_migrate
"""

_COUNT_REMAINING = """
MATCH (n:MetaObservation)
WHERE NOT n:Memory
RETURN count(n) AS remaining
"""

_LIST_SILOS = """
MATCH (n:MetaObservation)
WHERE n.silo_id IS NOT NULL
RETURN DISTINCT n.silo_id AS silo_id
"""


async def migrate_silo(client: MemgraphClient, silo_id: str, *, dry_run: bool = False) -> int:
    log = get_logger(__name__)
    if dry_run:
        rows: list[dict[str, Any]] = await client.execute_query(_DRY_RUN_SILO, {"silo_id": silo_id})
        count: int = rows[0]["would_migrate"] if rows else 0
        log.info("silo_dry_run", silo_id=silo_id, would_migrate=count)
        return count
    rows = await client.execute_write(_MIGRATE_SILO, {"silo_id": silo_id})
    processed: int = rows[0]["processed"] if rows else 0
    log.info("silo_migrated", silo_id=silo_id, processed=processed)
    return processed


async def list_silos(client: MemgraphClient) -> list[str]:
    rows: list[dict[str, Any]] = await client.execute_query(_LIST_SILOS)
    return [str(row["silo_id"]) for row in rows]


async def verify(client: MemgraphClient) -> int:
    rows: list[dict[str, Any]] = await client.execute_query(_COUNT_REMAINING)
    remaining: int = rows[0]["remaining"] if rows else 0
    return remaining


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate MetaObservation nodes to Memory{memory_type:'reflection'}."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--silo-id", metavar="ID", help="Migrate a single silo.")
    group.add_argument("--all-silos", action="store_true", help="Discover and migrate all silos.")
    group.add_argument(
        "--verify",
        action="store_true",
        help="Check that no MetaObservation nodes remain. Exits non-zero if any exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print count of nodes that would be migrated without mutating.",
    )
    args = parser.parse_args()

    configure_logging()
    log = get_logger(__name__)
    settings = get_settings()

    driver = create_memgraph_driver(settings.memgraph)
    client = MemgraphClient(driver)

    try:
        if args.verify:
            remaining = await verify(client)
            if remaining:
                log.error("verify_failed", remaining=remaining)
                sys.exit(1)
            log.info("verify_passed", remaining=0)
            return

        if args.silo_id:
            total = await migrate_silo(client, args.silo_id, dry_run=args.dry_run)
            log.info("migration_complete", total=total, dry_run=args.dry_run)
        else:
            silos = await list_silos(client)
            if not silos:
                log.info("no_meta_observations_found")
                return
            total = 0
            for silo_id in silos:
                total += await migrate_silo(client, silo_id, dry_run=args.dry_run)
            log.info("migration_complete", silos=len(silos), total=total, dry_run=args.dry_run)
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
