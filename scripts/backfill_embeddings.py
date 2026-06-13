#!/usr/bin/env python3
"""Backfill embeddings for all nodes in Memgraph to Qdrant.

Run locally pointing at beta:
    MEMGRAPH_URI=bolt://localhost:7687 \
    QDRANT_URL=http://localhost:6333 \
    uv run python scripts/backfill_embeddings.py

Or on beta via SSH:
    gcloud compute ssh engrammic-beta-stateful --zone europe-north1-a --tunnel-through-iap \
        --command "cd /opt/engrammic && docker compose exec dagster-code-server python -c '...' "
"""

import asyncio
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def main():
    from neo4j import AsyncGraphDatabase
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointStruct

    from context_service.embeddings import build_embedding_service

    MEMGRAPH_URI = os.getenv("MEMGRAPH_URI", "bolt://localhost:7687")
    QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
    COLLECTION = "engrammic"
    BATCH_SIZE = 4  # Match production batch size (Vertex AI token limits)

    print(f"Connecting to Memgraph at {MEMGRAPH_URI}")
    print(f"Connecting to Qdrant at {QDRANT_URL}")

    driver = AsyncGraphDatabase.driver(MEMGRAPH_URI)
    qdrant = AsyncQdrantClient(url=QDRANT_URL)
    embedder = build_embedding_service()

    # Fetch all nodes with content
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            WHERE n.content IS NOT NULL AND n.content <> ''
            RETURN n.id AS id, n.silo_id AS silo_id, n.content AS content, labels(n) AS labels
            """
        )
        nodes = [dict(r) async for r in result]

    print(f"Found {len(nodes)} nodes with content")

    if not nodes:
        print("Nothing to backfill")
        await driver.close()
        await qdrant.close()
        return

    # Process in batches
    total_embedded = 0
    total_failed = 0

    for i in range(0, len(nodes), BATCH_SIZE):
        batch = nodes[i : i + BATCH_SIZE]
        texts = [n["content"] for n in batch]

        try:
            vectors = await embedder.embed(texts)
        except Exception as e:
            print(f"Embedding error batch {i // BATCH_SIZE + 1}: {e}")
            total_failed += len(batch)
            continue

        # Upsert to Qdrant
        points = [
            PointStruct(
                id=n["id"],
                vector=vec,
                payload={
                    "silo_id": n["silo_id"],
                    "type": n["labels"][0] if n["labels"] else "Node",
                },
            )
            for n, vec in zip(batch, vectors)
        ]

        try:
            await qdrant.upsert(collection_name=COLLECTION, points=points)
            total_embedded += len(points)
            print(f"Batch {i // BATCH_SIZE + 1}/{(len(nodes) + BATCH_SIZE - 1) // BATCH_SIZE}: embedded {len(points)} nodes")
        except Exception as e:
            print(f"Qdrant upsert error batch {i // BATCH_SIZE + 1}: {e}")
            total_failed += len(batch)

    print(f"\nDone: {total_embedded} embedded, {total_failed} failed")

    await driver.close()
    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
