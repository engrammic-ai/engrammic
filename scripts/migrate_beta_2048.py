#!/usr/bin/env python3
"""One-time migration: fix Qdrant 768->2048 dims and create Memgraph text index.

Run on beta:
    gcloud compute ssh engrammic-beta-stateful --zone europe-north1-a --tunnel-through-iap \
        --command "cd /opt/engrammic && docker compose exec api python scripts/migrate_beta_2048.py"
"""

import asyncio
import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from neo4j import AsyncGraphDatabase


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
MEMGRAPH_URI = os.getenv("MEMGRAPH_URI", "bolt://localhost:7687")
MEMGRAPH_USER = os.getenv("MEMGRAPH_USER", "")
MEMGRAPH_PASSWORD = os.getenv("MEMGRAPH_PASSWORD", "")

COLLECTION_NAME = "engrammic"
NEW_DIMS = 2048


def migrate_qdrant():
    """Recreate Qdrant collection with 2048 dimensions."""
    print(f"Connecting to Qdrant at {QDRANT_URL}...")
    client = QdrantClient(url=QDRANT_URL)

    # Check current collection
    try:
        info = client.get_collection(COLLECTION_NAME)
        current_dims = info.config.params.vectors.size
        print(f"Current collection: {COLLECTION_NAME}, dims={current_dims}")

        if current_dims == NEW_DIMS:
            print("Already at 2048 dims, skipping Qdrant migration.")
            return

        # Get point count before deletion
        point_count = info.points_count
        print(f"Will delete {point_count} points and recreate with {NEW_DIMS} dims")

        # Delete and recreate
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted collection {COLLECTION_NAME}")

    except Exception as e:
        print(f"Collection doesn't exist or error: {e}")

    # Create with new dims
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=NEW_DIMS, distance=Distance.COSINE),
    )
    print(f"Created collection {COLLECTION_NAME} with {NEW_DIMS} dims")


async def migrate_memgraph():
    """Create text search index on Node.content."""
    print(f"Connecting to Memgraph at {MEMGRAPH_URI}...")

    auth = (MEMGRAPH_USER, MEMGRAPH_PASSWORD) if MEMGRAPH_USER else None
    driver = AsyncGraphDatabase.driver(MEMGRAPH_URI, auth=auth)

    async with driver.session() as session:
        # Check if index exists
        result = await session.run("CALL text_search.info() YIELD * RETURN *")
        indexes = [r async for r in result]

        existing = [i for i in indexes if i.get("index_name") == "node_content"]
        if existing:
            print("Text index 'node_content' already exists, skipping.")
        else:
            print("Creating text index 'node_content' on Node.content...")
            await session.run(
                'CALL text_search.create_index("node_content", "Node", "content")'
            )
            print("Text index created.")

    await driver.close()


async def main():
    print("=== Beta Migration: 2048 dims + text index ===\n")

    migrate_qdrant()
    print()
    await migrate_memgraph()

    print("\n=== Migration complete ===")
    print("Note: Existing vectors were deleted. Re-embed by re-storing nodes or running backfill.")


if __name__ == "__main__":
    asyncio.run(main())
