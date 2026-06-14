#!/usr/bin/env python3
"""Backfill Postgres nodes table from Memgraph for BM25 search.

Run after deploying migration 0017, before enabling BM25 channel.

Usage:
    uv run python scripts/backfill_postgres_nodes.py

Environment variables:
    MEMGRAPH_URI   Bolt URI for Memgraph (default: bolt://localhost:7687)
    DATABASE_URL   asyncpg-compatible Postgres DSN (required)
    BATCH_SIZE     Insert batch size (default: 500)

Example against beta via port-forward:
    MEMGRAPH_URI=bolt://localhost:7687 \\
    DATABASE_URL=postgresql://user:pass@localhost:5432/engrammic \\
    uv run python scripts/backfill_postgres_nodes.py
"""

import asyncio
import os
import sys
import uuid

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def main() -> None:
    import asyncpg
    from neo4j import AsyncGraphDatabase

    MEMGRAPH_URI = os.getenv("MEMGRAPH_URI", "bolt://localhost:7687")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to Memgraph at {MEMGRAPH_URI}")
    print(f"Connecting to Postgres at {DATABASE_URL.split('@')[-1]}")  # omit creds

    driver = AsyncGraphDatabase.driver(MEMGRAPH_URI)
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)

    try:
        # Fetch all nodes with content from Memgraph.
        # COALESCE handles nodes written before the layer/state properties were
        # standardised, falling back to safe defaults.
        cypher = """
        MATCH (n:Node)
        WHERE n.content IS NOT NULL AND n.content <> ''
        RETURN n.id AS id,
               n.silo_id AS silo_id,
               COALESCE(n.properties.layer, 'memory') AS layer,
               n.content AS content,
               COALESCE(n.properties.state, 'ACTIVE') AS state
        """

        print("Fetching nodes from Memgraph...")
        async with driver.session() as session:
            result = await session.run(cypher)
            rows = [dict(r) async for r in result]

        print(f"Found {len(rows)} nodes with content")

        if not rows:
            print("Nothing to backfill.")
            return

        # Coerce id and silo_id to uuid.UUID objects; skip rows where either
        # field is missing or unparseable so a single bad node does not abort
        # the whole run.
        records: list[tuple[uuid.UUID, uuid.UUID, str, str, str]] = []
        skipped = 0
        for r in rows:
            try:
                node_id = uuid.UUID(str(r["id"]))
                silo_id = uuid.UUID(str(r["silo_id"]))
            except (TypeError, ValueError) as exc:
                print(f"  SKIP row (bad uuid): {r.get('id')!r} / {r.get('silo_id')!r}: {exc}")
                skipped += 1
                continue

            layer: str = r["layer"] or "memory"
            content: str = r["content"] or ""
            state: str = r["state"] or "ACTIVE"

            records.append((node_id, silo_id, layer, content, state))

        if skipped:
            print(f"Skipped {skipped} rows with unparseable IDs")

        # Batch insert to Postgres with ON CONFLICT DO NOTHING for idempotency.
        # Handles both ACTIVE and SUPERSEDED states as returned by Memgraph.
        total_inserted = 0
        total_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE

        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1

            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO nodes (id, silo_id, layer, content, state, created_at)
                    VALUES ($1, $2, $3, $4, $5, now())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    batch,
                )

            total_inserted += len(batch)
            print(f"  Batch {batch_num}/{total_batches}: inserted {len(batch)} rows")

        print(f"\nDone: {total_inserted} rows written, {skipped} skipped")

    finally:
        await driver.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
