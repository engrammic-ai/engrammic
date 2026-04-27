"""Migrate legacy BELONGS_TO edges to MEMBER_OF in Memgraph.

Usage:
    uv run python -m scripts.migrate_belongs_to --silo-id <id>
    uv run python -m scripts.migrate_belongs_to --all-silos
    uv run python -m scripts.migrate_belongs_to --verify

Smoke check (requires live docker stack with seeded BELONGS_TO data):
    uv run python -m scripts.migrate_belongs_to --all-silos
    uv run python -m scripts.migrate_belongs_to --verify

The migration is idempotent: MERGE ensures that if MEMBER_OF already exists
the edge is not duplicated, and DELETE r removes BELONGS_TO so a re-run is a no-op.
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
MATCH (n)-[r:BELONGS_TO]->(c:Cluster {silo_id: $silo_id})
MERGE (n)-[r2:MEMBER_OF]->(c)
  ON CREATE SET r2.weight = r.weight,
               r2.created_at = r.created_at,
               r2.migrated_from = 'BELONGS_TO'
DELETE r
RETURN count(r2) AS migrated
"""

_COUNT_BELONGS_TO = """
MATCH ()-[r:BELONGS_TO]->()
RETURN count(r) AS remaining
"""

_LIST_SILOS = """
MATCH (s:Silo)
RETURN s.id AS silo_id
"""


async def migrate_silo(client: MemgraphClient, silo_id: str) -> int:
    """Migrate BELONGS_TO -> MEMBER_OF for one silo. Returns count of edges touched."""
    log = get_logger(__name__)
    rows: list[dict[str, Any]] = await client.execute_write(
        _MIGRATE_SILO, {"silo_id": silo_id}
    )
    migrated: int = rows[0]["migrated"] if rows else 0
    log.info("silo_migrated", silo_id=silo_id, migrated=migrated)
    return migrated


async def list_silos(client: MemgraphClient) -> list[str]:
    """Return all silo IDs known to Memgraph."""
    rows: list[dict[str, Any]] = await client.execute_query(_LIST_SILOS)
    return [str(row["silo_id"]) for row in rows]


async def verify(client: MemgraphClient) -> int:
    """Return the count of remaining BELONGS_TO edges (0 = clean)."""
    rows: list[dict[str, Any]] = await client.execute_query(_COUNT_BELONGS_TO)
    remaining: int = rows[0]["remaining"] if rows else 0
    return remaining


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate BELONGS_TO edges to MEMBER_OF in Memgraph."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--silo-id", metavar="ID", help="Migrate a single silo.")
    group.add_argument(
        "--all-silos", action="store_true", help="Discover and migrate all silos."
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Check that no BELONGS_TO edges remain. Exits non-zero if any exist.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)
    log = get_logger(__name__)

    driver = await create_memgraph_driver(settings)
    client = MemgraphClient(driver)

    try:
        if args.verify:
            remaining = await verify(client)
            if remaining > 0:
                log.error(
                    "verify_failed",
                    remaining_belongs_to=remaining,
                    message="BELONGS_TO edges still present; migration incomplete.",
                )
                sys.exit(1)
            log.info("verify_passed", remaining_belongs_to=0)
            return

        if args.silo_id:
            silo_ids = [args.silo_id]
        else:
            silo_ids = await list_silos(client)
            log.info("discovered_silos", count=len(silo_ids))

        total_migrated = 0
        for silo_id in silo_ids:
            total_migrated += await migrate_silo(client, silo_id)

        log.info("migration_complete", total_migrated=total_migrated, silos=len(silo_ids))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
