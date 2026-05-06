"""Backfill SPLADE sparse vectors for nodes that have only dense embeddings.

Usage:
    uv run python -m scripts.backfill_splade --silo-id <id>
    uv run python -m scripts.backfill_splade --all-silos
    uv run python -m scripts.backfill_splade --dry-run --silo-id <id>
    uv run python -m scripts.backfill_splade --dry-run --all-silos

The script scans Qdrant for points that have a dense vector but lack a sparse
vector, re-encodes them via SPLADE, and upserts the sparse vector alongside the
existing dense one.  It is idempotent: running it twice on the same data set is
a no-op because Qdrant UPSERT overwrites in-place.

Requires:
    - A running Qdrant instance (configured via QDRANT_URL / .env).
    - A running Memgraph instance (to resolve silo IDs when --all-silos is used).
    - The ``splade`` extra installed: uv sync --extra splade
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import DENSE_VECTOR_NAME, QdrantClient, get_collection_name

_BATCH_SIZE = 100

# Lists all distinct silo IDs that appear in the main node collection (Memgraph).
_LIST_SILOS = """
MATCH (n:Node)
WHERE n.silo_id IS NOT NULL
RETURN DISTINCT n.silo_id AS silo_id
"""


async def _list_silos(client: MemgraphClient) -> list[str]:
    rows: list[dict[str, Any]] = await client.execute_query(_LIST_SILOS)
    return [str(row["silo_id"]) for row in rows]


async def _backfill_silo(
    qdrant_client: QdrantClient,
    encoder: SpladeEncoder,
    silo_id: str,
    *,
    dry_run: bool = False,
) -> int:
    """Backfill sparse vectors for one silo.

    Scrolls through all Qdrant points for the silo and re-encodes any that
    lack a sparse vector.  Returns the number of points updated (or that
    would be updated in dry-run mode).
    """
    log = get_logger(__name__)
    client = await qdrant_client._get_client()
    collection = get_collection_name(silo_id)

    # Check collection exists.
    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}
    if collection not in existing:
        log.warning("backfill_collection_missing", collection=collection, silo_id=silo_id)
        return 0

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    query_filter = Filter(
        must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
    )

    total_updated = 0
    offset: str | int | None = None

    while True:
        scroll_result = await client.scroll(
            collection_name=collection,
            scroll_filter=query_filter,
            limit=_BATCH_SIZE,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )
        points, next_offset = scroll_result

        if not points:
            break

        # Determine which points lack sparse vectors.
        needs_sparse: list[Any] = []
        for p in points:
            vectors = p.vector
            if isinstance(vectors, dict):
                # Named-vector format — has sparse only if sparse key present.
                if DENSE_VECTOR_NAME not in vectors:
                    # Dense vector absent in this point; skip (malformed).
                    continue
                # sparse key would be "sparse"; if absent, needs backfill.
                if "sparse" not in vectors:
                    needs_sparse.append(p)
            # Plain vector format (non-hybrid collection): always backfill.
            else:
                needs_sparse.append(p)

        if needs_sparse and not dry_run:
            # Re-fetch content from payload (node_id -> look up in Memgraph is expensive;
            # instead we rely on any stored "content" payload key, falling back to node_id
            # as a sentinel so SPLADE at least encodes *something*).
            texts = [
                str(p.payload.get("content") or p.payload.get("node_id") or str(p.id))
                for p in needs_sparse
                if p.payload is not None
            ]
            if not texts:
                texts = [str(p.id) for p in needs_sparse]

            try:
                sparse_vecs = await encoder.encode_batch(texts)
            except SpladeEncoderError as exc:
                log.error("backfill_encode_error", silo_id=silo_id, error=str(exc))
                if next_offset is None:
                    break
                offset = next_offset
                continue

            from qdrant_client.models import PointStruct, SparseVector

            updated_points: list[PointStruct] = []
            for p, sparse in zip(needs_sparse, sparse_vecs, strict=False):
                indices, values = encoder.to_qdrant(sparse)
                if not indices:
                    continue

                # Preserve existing payload.
                existing_payload = dict(p.payload or {})

                # Rebuild vector dict — dense from existing, sparse from encoder.
                existing_vectors = p.vector
                if isinstance(existing_vectors, dict):
                    dense_vec: list[float] = existing_vectors.get(DENSE_VECTOR_NAME, [])  # type: ignore[assignment]
                else:
                    dense_vec = list(existing_vectors or [])

                updated_points.append(
                    PointStruct(
                        id=p.id,
                        vector={
                            DENSE_VECTOR_NAME: dense_vec,
                            "sparse": SparseVector(indices=indices, values=values),
                        },
                        payload=existing_payload,
                    )
                )

            if updated_points:
                await client.upsert(collection_name=collection, points=updated_points)
                log.info(
                    "backfill_batch_upserted",
                    silo_id=silo_id,
                    count=len(updated_points),
                )

        total_updated += len(needs_sparse)

        if next_offset is None:
            break
        offset = next_offset

    if dry_run:
        log.info("backfill_dry_run", silo_id=silo_id, would_update=total_updated)
    else:
        log.info("backfill_complete", silo_id=silo_id, updated=total_updated)
    return total_updated


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill SPLADE sparse vectors for Qdrant points that have only dense."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--silo-id", metavar="ID", help="Backfill a single silo.")
    group.add_argument(
        "--all-silos",
        action="store_true",
        help="Discover and backfill all silos via Memgraph.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count points that would be updated without writing.",
    )
    parser.add_argument(
        "--model",
        default="prithivida/Splade_PP_en_v1",
        help="SPLADE model name (default: prithivida/Splade_PP_en_v1).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)
    log = get_logger(__name__)

    encoder = SpladeEncoder(model_name=args.model)
    qdrant = QdrantClient.from_settings(settings)

    if args.all_silos:
        driver = await create_memgraph_driver(settings)
        memgraph = MemgraphClient(driver)
        try:
            silo_ids = await _list_silos(memgraph)
        finally:
            await memgraph.close()
        log.info("backfill_discovered_silos", count=len(silo_ids))
    else:
        silo_ids = [args.silo_id]

    total = 0
    for silo_id in silo_ids:
        total += await _backfill_silo(qdrant, encoder, silo_id, dry_run=args.dry_run)

    if args.dry_run:
        log.info("backfill_dry_run_total", would_update=total, silos=len(silo_ids))
    else:
        log.info("backfill_total", updated=total, silos=len(silo_ids))

    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
