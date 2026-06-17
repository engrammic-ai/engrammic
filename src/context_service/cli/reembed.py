"""CLI command to re-embed all nodes with current embedding model.

Use this when changing embedding models to preserve data while updating vectors.

Usage:
    uv run python -m context_service.cli.reembed --silo-id <uuid>
    uv run python -m context_service.cli.reembed --all-silos
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService
from context_service.engine import queries
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import QdrantClient

logger = get_logger(__name__)

BATCH_SIZE = 100


async def get_all_silos(memgraph: MemgraphClient) -> list[str]:
    """Get all silo IDs from the database."""
    result = await memgraph.execute_query(queries.LIST_SILOS, {})
    return [r["silo_id"] for r in result]


async def get_nodes_batch(
    memgraph: MemgraphClient, silo_id: str, offset: int, limit: int
) -> list[dict[str, Any]]:
    """Get a batch of nodes from the database."""
    result = await memgraph.execute_query(
        queries.EXPORT_ALL_NODES,
        {"silo_id": silo_id, "offset": offset, "limit": limit},
    )
    return result


async def reembed_silo(
    silo_id: str,
    memgraph: MemgraphClient,
    qdrant: QdrantClient,
    embedding_service: LiteLLMEmbeddingService,
    dry_run: bool = False,
) -> int:
    """Re-embed all nodes in a silo.

    Returns:
        Number of nodes re-embedded.
    """
    total = 0
    offset = 0

    print(f"Re-embedding silo: {silo_id}")

    while True:
        nodes = await get_nodes_batch(memgraph, silo_id, offset, BATCH_SIZE)
        if not nodes:
            break

        contents = []
        node_ids = []

        for node_data in nodes:
            node = node_data.get("n", node_data)
            node_id = node.get("id")
            content = node.get("content")

            if not content or not node_id:
                continue

            contents.append(content)
            node_ids.append(node_id)

        if contents:
            if dry_run:
                print(f"  [dry-run] Would re-embed {len(contents)} nodes (offset {offset})")
            else:
                embeddings = await embedding_service.embed(contents)

                for node_id, embedding in zip(node_ids, embeddings, strict=True):
                    await qdrant.upsert(
                        node_id=node_id,
                        vector=embedding,
                        payload={"silo_id": silo_id},
                    )

                print(f"  Re-embedded {len(contents)} nodes (offset {offset})")

            total += len(contents)

        offset += BATCH_SIZE

    return total


async def main(args: argparse.Namespace) -> int:
    """Main entry point."""
    settings = get_settings()

    driver = await create_memgraph_driver(settings)
    memgraph = MemgraphClient(driver)

    qdrant = QdrantClient.from_settings(settings)
    await qdrant.ensure_collection(hybrid=False)

    embedding_service = LiteLLMEmbeddingService(
        model=settings.models.litellm_embedding_model,
        dimensions=settings.models.embedding_dimensions,
    )

    try:
        if args.all_silos:
            silos = await get_all_silos(memgraph)
            print(f"Found {len(silos)} silos to process")
        elif args.silo_id:
            try:
                uuid.UUID(args.silo_id)
            except ValueError:
                print(f"Error: Invalid silo ID: {args.silo_id}", file=sys.stderr)
                return 1
            silos = [args.silo_id]
        else:
            print("Error: Specify --silo-id or --all-silos", file=sys.stderr)
            return 1

        total_nodes = 0
        for silo_id in silos:
            count = await reembed_silo(
                silo_id,
                memgraph,
                qdrant,
                embedding_service,
                dry_run=args.dry_run,
            )
            total_nodes += count

        action = "Would re-embed" if args.dry_run else "Re-embedded"
        print(f"\n{action} {total_nodes} nodes across {len(silos)} silo(s)")
        return 0

    finally:
        await memgraph.close()


def cli() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Re-embed all nodes with current embedding model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--silo-id",
        help="Silo ID to re-embed (UUID)",
    )
    parser.add_argument(
        "--all-silos",
        action="store_true",
        help="Re-embed all silos",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))


if __name__ == "__main__":
    cli()
