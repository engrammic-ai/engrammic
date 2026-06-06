#!/usr/bin/env python3
"""Migrate Qdrant collections from non-hybrid to hybrid schema.

Copies all points from collections with unnamed vectors to new collections
with named vectors (dense/sparse), preserving all data.

Usage:
    uv run python scripts/migrate_qdrant_to_hybrid.py --dry-run
    uv run python scripts/migrate_qdrant_to_hybrid.py --execute
"""

import argparse
import asyncio
import os
import sys

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


COLLECTION_PREFIX = "ctx_"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
BATCH_SIZE = 100


async def get_collections_to_migrate(client: AsyncQdrantClient) -> list[str]:
    """Find ctx_* collections that need migration (have unnamed vectors)."""
    collections = await client.get_collections()
    to_migrate = []

    for c in collections.collections:
        if not c.name.startswith(COLLECTION_PREFIX):
            continue

        info = await client.get_collection(c.name)
        vectors_config = info.config.params.vectors

        # If vectors_config is VectorParams (not dict), it's unnamed
        if isinstance(vectors_config, VectorParams):
            to_migrate.append(c.name)
            print(f"  {c.name}: unnamed vectors, needs migration")
        elif isinstance(vectors_config, dict):
            if DENSE_VECTOR_NAME in vectors_config:
                print(f"  {c.name}: already hybrid, skipping")
            else:
                print(f"  {c.name}: named vectors but no 'dense', skipping")
        else:
            print(f"  {c.name}: unknown config type, skipping")

    return to_migrate


async def migrate_collection(
    client: AsyncQdrantClient,
    old_name: str,
    vector_size: int,
    dry_run: bool = True,
) -> bool:
    """Migrate a single collection to hybrid schema."""
    new_name = f"{old_name}_hybrid"

    # Get point count
    info = await client.get_collection(old_name)
    point_count = info.points_count
    print(f"\n  Migrating {old_name} ({point_count} points) -> {new_name}")

    if dry_run:
        print(f"  [DRY RUN] Would create {new_name} with hybrid schema")
        print(f"  [DRY RUN] Would copy {point_count} points")
        print(f"  [DRY RUN] Would delete {old_name}")
        print(f"  [DRY RUN] Would rename {new_name} -> {old_name}")
        return True

    # Create new collection with hybrid schema (delete if exists from failed run)
    try:
        await client.delete_collection(new_name)
        print(f"  Deleted stale {new_name}")
    except Exception:
        pass

    await client.create_collection(
        collection_name=new_name,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: {},
        },
    )
    print(f"  Created {new_name} with hybrid schema")

    # Copy points in batches
    offset = None
    copied = 0

    while True:
        points, offset = await client.scroll(
            collection_name=old_name,
            limit=BATCH_SIZE,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )

        if not points:
            break

        # Convert to hybrid format
        new_points = []
        for p in points:
            # Old format: p.vector is the unnamed vector (list[float])
            # New format: {"dense": vector}
            new_points.append(
                PointStruct(
                    id=p.id,
                    vector={DENSE_VECTOR_NAME: p.vector},
                    payload=p.payload,
                )
            )

        await client.upsert(collection_name=new_name, points=new_points)
        copied += len(new_points)
        print(f"  Copied {copied}/{point_count} points", end="\r")

        if offset is None:
            break

    print(f"  Copied {copied}/{point_count} points")

    # Delete old collection
    await client.delete_collection(old_name)
    print(f"  Deleted {old_name}")

    # Rename new collection to old name
    # Note: Qdrant doesn't have rename, so we create alias or just use new name
    # For now, we'll create with the final name directly

    # Actually, let's recreate with original name
    await client.create_collection(
        collection_name=old_name,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: {},
        },
    )

    # Copy from temp to original name
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=new_name,
            limit=BATCH_SIZE,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )

        if not points:
            break

        new_points = [
            PointStruct(
                id=p.id,
                vector=p.vector,  # Already in hybrid format
                payload=p.payload,
            )
            for p in points
        ]

        await client.upsert(collection_name=old_name, points=new_points)

        if offset is None:
            break

    # Delete temp collection
    await client.delete_collection(new_name)
    print(f"  Renamed {new_name} -> {old_name}")

    return True


async def main(dry_run: bool = True):
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    vector_size = int(os.environ.get("VECTOR_SIZE", "768"))

    print(f"Connecting to Qdrant at {qdrant_url}")
    print(f"Vector size: {vector_size}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}\n")

    client = AsyncQdrantClient(url=qdrant_url)

    try:
        print("Scanning collections...")
        to_migrate = await get_collections_to_migrate(client)

        if not to_migrate:
            print("\nNo collections need migration.")
            return

        print(f"\nFound {len(to_migrate)} collection(s) to migrate:")
        for name in to_migrate:
            print(f"  - {name}")

        if not dry_run:
            print("\nStarting migration...")
            for name in to_migrate:
                success = await migrate_collection(client, name, vector_size, dry_run=False)
                if not success:
                    print(f"  FAILED to migrate {name}")
                    return
            print("\nMigration complete!")
        else:
            print("\nRun with --execute to perform migration.")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Qdrant to hybrid schema")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Show what would be done")
    parser.add_argument("--execute", action="store_true", help="Actually perform migration")
    args = parser.parse_args()

    dry_run = not args.execute
    asyncio.run(main(dry_run=dry_run))
