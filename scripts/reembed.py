#!/usr/bin/env python3
"""Re-embed all nodes from Memgraph to Qdrant.

Usage:
    uv run python scripts/reembed.py --memgraph-host localhost --qdrant-url http://localhost:6333 --tei-url http://localhost:8080
"""

from __future__ import annotations

import asyncio
import argparse
import time
from typing import Any

import httpx
from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct


EMBEDDING_DIMENSIONS = 1024  # bge-m3
BATCH_SIZE = 32  # TEI max-client-batch-size


async def fetch_nodes(driver: Any, batch_size: int = 1000) -> list[dict]:
    """Fetch all nodes with content from Memgraph."""
    nodes = []
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            WHERE n.content IS NOT NULL AND n.content <> ''
            RETURN n.id AS id, n.content AS content, n.silo_id AS silo_id,
                   labels(n) AS labels, n.node_type AS node_type
            """
        )
        async for record in result:
            nodes.append({
                "id": record["id"],
                "content": record["content"],
                "silo_id": record["silo_id"],
                "labels": record["labels"],
                "node_type": record["node_type"] or (record["labels"][0] if record["labels"] else "Node"),
            })
    return nodes


async def embed_batch(texts: list[str], tei_url: str, client: httpx.AsyncClient) -> list[list[float]]:
    """Embed texts via TEI."""
    response = await client.post(
        f"{tei_url}/embed",
        json={"inputs": texts},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


async def reembed(
    memgraph_host: str,
    memgraph_port: int,
    qdrant_url: str,
    tei_url: str,
    collection: str = "engrammic",
    dry_run: bool = False,
) -> dict:
    """Re-embed all nodes."""
    print(f"Connecting to Memgraph at {memgraph_host}:{memgraph_port}")
    driver = AsyncGraphDatabase.driver(
        f"bolt://{memgraph_host}:{memgraph_port}",
        auth=("", ""),
    )

    print("Fetching nodes from Memgraph...")
    nodes = await fetch_nodes(driver)
    print(f"Found {len(nodes)} nodes with content")

    if not nodes:
        await driver.close()
        return {"nodes": 0, "embedded": 0}

    if dry_run:
        print(f"[DRY RUN] Would embed {len(nodes)} nodes")
        await driver.close()
        return {"nodes": len(nodes), "embedded": 0, "dry_run": True}

    print(f"Embedding via TEI at {tei_url}...")
    qdrant = AsyncQdrantClient(url=qdrant_url)
    http_client = httpx.AsyncClient()

    embedded = 0
    start = time.perf_counter()

    # Batch embed and upsert
    for i in range(0, len(nodes), BATCH_SIZE):
        batch = nodes[i:i + BATCH_SIZE]
        texts = [n["content"][:2000] for n in batch]  # truncate

        embeddings = await embed_batch(texts, tei_url, http_client)

        points = [
            PointStruct(
                id=n["id"],
                vector=emb,
                payload={
                    "content": n["content"][:5000],
                    "silo_id": n["silo_id"],
                    "node_type": n["node_type"],
                },
            )
            for n, emb in zip(batch, embeddings)
        ]

        await qdrant.upsert(collection_name=collection, points=points)
        embedded += len(points)

        if (i // BATCH_SIZE) % 10 == 0:
            print(f"  Progress: {embedded}/{len(nodes)} ({100*embedded/len(nodes):.1f}%)")

    elapsed = time.perf_counter() - start
    print(f"Done: {embedded} nodes in {elapsed:.1f}s ({embedded/elapsed:.1f} nodes/sec)")

    await http_client.aclose()
    await qdrant.close()
    await driver.close()

    return {"nodes": len(nodes), "embedded": embedded, "elapsed_sec": elapsed}


def main():
    parser = argparse.ArgumentParser(description="Re-embed nodes from Memgraph to Qdrant")
    parser.add_argument("--memgraph-host", default="localhost")
    parser.add_argument("--memgraph-port", type=int, default=7687)
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--tei-url", default="http://localhost:8080")
    parser.add_argument("--collection", default="engrammic")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(reembed(
        memgraph_host=args.memgraph_host,
        memgraph_port=args.memgraph_port,
        qdrant_url=args.qdrant_url,
        tei_url=args.tei_url,
        collection=args.collection,
        dry_run=args.dry_run,
    ))
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
