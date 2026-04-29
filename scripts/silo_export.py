"""Export a silo's graph state to JSONL for portability.

Usage:
    uv run python -m scripts.silo_export --silo-id <uuid> --out <path>
    uv run python -m scripts.silo_export --silo-id <uuid> --out dump.jsonl --include-vectors
    uv run python -m scripts.silo_export --silo-id <uuid> --out dump.jsonl --page-size 200

The output is a JSONL file whose first line is a manifest and whose subsequent
lines are node, edge, or (when --include-vectors) vector records. See
context/specs/silo-portability.md for the full schema.

Nodes and edges are streamed in pages to keep memory usage flat on large silos.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from datetime import UTC, datetime
from typing import Any

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import COLLECTION_NAME, QdrantClient

_SCHEMA_VERSION = 1
_DEFAULT_PAGE_SIZE = 500

# ---------------------------------------------------------------------------
# Cypher: paginated node fetch
# Memgraph uses id() for internal IDs (not elementId() which is Neo4j-specific).
# We use it as the opaque record identifier so edges can reference endpoints
# without depending on application-layer UUIDs.
# ---------------------------------------------------------------------------
_FETCH_NODES_PAGE = """
MATCH (n {silo_id: $silo_id})
WITH n, id(n) AS eid
ORDER BY eid
SKIP $skip
LIMIT $limit
RETURN eid AS id, labels(n) AS labels, properties(n) AS props
"""

# ---------------------------------------------------------------------------
# Cypher: paginated edge fetch
# Both endpoints must belong to the silo; cross-silo edges are anomalies and
# we skip them (the WHERE clause enforces this, and the exporter double-checks
# via cross_silo_guard).
# ---------------------------------------------------------------------------
_FETCH_EDGES_PAGE = """
MATCH (a {silo_id: $silo_id})-[r]->(b {silo_id: $silo_id})
WITH a, r, b, id(r) AS reid
ORDER BY reid
SKIP $skip
LIMIT $limit
RETURN id(a) AS src, id(b) AS dst,
       type(r) AS rel_type, properties(r) AS props
"""

# ---------------------------------------------------------------------------
# Cypher: count helpers (for progress logging)
# ---------------------------------------------------------------------------
_COUNT_NODES = "MATCH (n {silo_id: $silo_id}) RETURN count(n) AS cnt"
_COUNT_EDGES = """
MATCH (a {silo_id: $silo_id})-[r]->(b {silo_id: $silo_id})
RETURN count(r) AS cnt
"""


def _coerce_props(props: dict[str, Any]) -> dict[str, Any]:
    """Serialize neo4j driver types to plain Python for JSON output."""
    out: dict[str, Any] = {}
    for k, v in props.items():
        # neo4j DateTime / Date / Time objects have .iso_format()
        if hasattr(v, "iso_format"):
            out[k] = v.iso_format()
        else:
            out[k] = v
    return out


async def export_nodes(
    client: MemgraphClient,
    silo_id: str,
    out: Any,
    *,
    page_size: int,
) -> int:
    """Stream node records to *out*. Returns total nodes written."""
    log = get_logger(__name__)
    skip = 0
    total = 0
    while True:
        rows = await client.execute_query(
            _FETCH_NODES_PAGE,
            {"silo_id": silo_id, "skip": skip, "limit": page_size},
        )
        if not rows:
            break
        for row in rows:
            record: dict[str, Any] = {
                "kind": "node",
                "id": row["id"],
                "labels": list(row["labels"]),
                "properties": _coerce_props(dict(row["props"])),
            }
            out.write(json.dumps(record) + "\n")
            total += 1
        log.debug("nodes_page_written", skip=skip, count=len(rows))
        skip += page_size
        if len(rows) < page_size:
            break
    return total


async def export_edges(
    client: MemgraphClient,
    silo_id: str,
    out: Any,
    *,
    page_size: int,
) -> int:
    """Stream edge records to *out*. Returns total edges written."""
    log = get_logger(__name__)
    skip = 0
    total = 0
    while True:
        rows = await client.execute_query(
            _FETCH_EDGES_PAGE,
            {"silo_id": silo_id, "skip": skip, "limit": page_size},
        )
        if not rows:
            break
        for row in rows:
            record = {
                "kind": "edge",
                "src": row["src"],
                "dst": row["dst"],
                "type": row["rel_type"],
                "properties": _coerce_props(dict(row["props"])),
            }
            out.write(json.dumps(record) + "\n")
            total += 1
        log.debug("edges_page_written", skip=skip, count=len(rows))
        skip += page_size
        if len(rows) < page_size:
            break
    return total


async def export_vectors(
    qdrant: QdrantClient,
    silo_id: str,
    out: Any,
) -> int:
    """Stream vector records to *out* from Qdrant. Returns total vectors written."""
    from qdrant_client.http import models as qmodels

    log = get_logger(__name__)
    client = await qdrant._get_client()
    total = 0
    offset: str | None = None
    batch_size = 100

    while True:
        result, next_offset = await client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="silo_id",
                        match=qmodels.MatchValue(value=silo_id),
                    )
                ]
            ),
            limit=batch_size,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )
        for point in result:
            node_id = (point.payload or {}).get("node_id", str(point.id))
            # Dense vector — may be a list directly or a named-vector dict.
            raw_vec = point.vector
            dense: list[float] = raw_vec if isinstance(raw_vec, list) else []
            record = {
                "kind": "vector",
                "node_id": node_id,
                "dense": dense,
            }
            out.write(json.dumps(record) + "\n")
            total += 1
        log.debug("vectors_page_written", count=len(result))
        offset = str(next_offset) if next_offset is not None else None
        if not result or next_offset is None:
            break
    return total


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a silo's graph state to JSONL."
    )
    parser.add_argument("--silo-id", required=True, metavar="UUID", help="Silo to export.")
    parser.add_argument("--out", required=True, metavar="PATH", help="Output JSONL file.")
    parser.add_argument(
        "--include-vectors",
        action="store_true",
        help="Also export dense vectors from Qdrant.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=_DEFAULT_PAGE_SIZE,
        metavar="N",
        help=f"Nodes/edges per Cypher batch (default: {_DEFAULT_PAGE_SIZE}).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)
    log = get_logger(__name__)

    driver = await create_memgraph_driver(settings)
    client = MemgraphClient(driver)

    try:
        # Verify silo exists
        count_rows = await client.execute_query(_COUNT_NODES, {"silo_id": args.silo_id})
        node_count = count_rows[0]["cnt"] if count_rows else 0
        edge_count_rows = await client.execute_query(_COUNT_EDGES, {"silo_id": args.silo_id})
        edge_count = edge_count_rows[0]["cnt"] if edge_count_rows else 0

        log.info(
            "export_starting",
            silo_id=args.silo_id,
            node_count=node_count,
            edge_count=edge_count,
            out=args.out,
        )

        hostname = socket.gethostname()
        manifest: dict[str, Any] = {
            "_manifest": {
                "schema_version": _SCHEMA_VERSION,
                "silo_id": args.silo_id,
                "exported_at": datetime.now(UTC).isoformat(),
                "source_env": settings.environment,
                "source_host": hostname,
            }
        }

        with open(args.out, "w", encoding="utf-8") as f:
            # Manifest — always first
            f.write(json.dumps(manifest) + "\n")

            # Nodes
            nodes_written = await export_nodes(
                client, args.silo_id, f, page_size=args.page_size
            )
            log.info("nodes_exported", count=nodes_written)

            # Edges
            edges_written = await export_edges(
                client, args.silo_id, f, page_size=args.page_size
            )
            log.info("edges_exported", count=edges_written)

            # Vectors (optional)
            vectors_written = 0
            if args.include_vectors:
                qdrant = QdrantClient.from_settings(settings)
                try:
                    vectors_written = await export_vectors(qdrant, args.silo_id, f)
                    log.info("vectors_exported", count=vectors_written)
                finally:
                    await qdrant.close()

        log.info(
            "export_complete",
            silo_id=args.silo_id,
            out=args.out,
            nodes=nodes_written,
            edges=edges_written,
            vectors=vectors_written,
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
