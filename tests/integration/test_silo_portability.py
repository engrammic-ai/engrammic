"""Round-trip integration test for silo export/import portability tooling.

Requires the live docker stack (Memgraph on 7687). Skipped automatically when
the stack is not reachable.

Test plan:
  1. Seed a silo with ~20 nodes and ~30 edges across multiple label types.
  2. Export to a temp JSONL file.
  3. Import into a fresh silo via --rename-silo (different UUID).
  4. Assert node count, edge count, and label sets match.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from context_service.stores import MemgraphClient
from scripts.silo_export import export_edges, export_nodes
from scripts.silo_import import SiloImporter

from .conftest import docker_available

# ---------------------------------------------------------------------------
# Seed queries
# ---------------------------------------------------------------------------

_SEED_CLAIM = """
MERGE (n:Claim {id: $id, silo_id: $silo_id, content: $content, layer: 'memory'})
RETURN n
"""

_SEED_FACT = """
MERGE (n:Fact {id: $id, silo_id: $silo_id, content: $content, layer: 'knowledge'})
RETURN n
"""

_SEED_CLUSTER = """
MERGE (c:Cluster {id: $id, silo_id: $silo_id, label: $label})
RETURN c
"""

_SEED_EDGE = """
MATCH (a {id: $src_id, silo_id: $silo_id}), (b {id: $dst_id, silo_id: $silo_id})
MERGE (a)-[r:REFERENCES {weight: $weight}]->(b)
RETURN r
"""

_SEED_MEMBER_OF = """
MATCH (n {id: $node_id, silo_id: $silo_id}), (c:Cluster {id: $cluster_id, silo_id: $silo_id})
MERGE (n)-[r:MEMBER_OF {weight: 1.0}]->(c)
RETURN r
"""

_COUNT_NODES = "MATCH (n {silo_id: $silo_id}) RETURN count(n) AS cnt"
_COUNT_EDGES = """
MATCH (a {silo_id: $silo_id})-[r]->(b {silo_id: $silo_id})
RETURN count(r) AS cnt
"""
_GET_LABELS = """
MATCH (n {silo_id: $silo_id})
RETURN DISTINCT labels(n) AS labels
"""


async def _seed_silo(client: MemgraphClient, silo_id: str) -> dict[str, Any]:
    """Seed ~20 nodes + ~30 edges. Returns expected counts."""
    claim_ids = [f"claim-{i}-{uuid.uuid4().hex[:6]}" for i in range(10)]
    fact_ids = [f"fact-{i}-{uuid.uuid4().hex[:6]}" for i in range(8)]
    cluster_ids = [f"cluster-{i}-{uuid.uuid4().hex[:6]}" for i in range(2)]

    # Nodes
    for cid in claim_ids:
        await client.execute_write(
            _SEED_CLAIM,
            {"id": cid, "silo_id": silo_id, "content": f"Claim content for {cid}"},
        )
    for fid in fact_ids:
        await client.execute_write(
            _SEED_FACT,
            {"id": fid, "silo_id": silo_id, "content": f"Fact content for {fid}"},
        )
    for i, clid in enumerate(cluster_ids):
        await client.execute_write(
            _SEED_CLUSTER,
            {"id": clid, "silo_id": silo_id, "label": f"cluster-{i}"},
        )

    # REFERENCES edges: chain claims, then facts
    edge_count = 0
    for i in range(len(claim_ids) - 1):
        await client.execute_write(
            _SEED_EDGE,
            {
                "src_id": claim_ids[i],
                "dst_id": claim_ids[i + 1],
                "silo_id": silo_id,
                "weight": 0.5 + i * 0.01,
            },
        )
        edge_count += 1
    for i in range(len(fact_ids) - 1):
        await client.execute_write(
            _SEED_EDGE,
            {
                "src_id": fact_ids[i],
                "dst_id": fact_ids[i + 1],
                "silo_id": silo_id,
                "weight": 0.7 + i * 0.01,
            },
        )
        edge_count += 1
    # Cross-type edges: claims -> facts
    for i in range(min(5, len(claim_ids), len(fact_ids))):
        await client.execute_write(
            _SEED_EDGE,
            {
                "src_id": claim_ids[i],
                "dst_id": fact_ids[i],
                "silo_id": silo_id,
                "weight": 0.9,
            },
        )
        edge_count += 1

    # MEMBER_OF edges: assign all claims/facts to clusters
    for i, cid in enumerate(claim_ids):
        cluster_id = cluster_ids[i % len(cluster_ids)]
        await client.execute_write(
            _SEED_MEMBER_OF,
            {"node_id": cid, "silo_id": silo_id, "cluster_id": cluster_id},
        )
        edge_count += 1
    for i, fid in enumerate(fact_ids):
        cluster_id = cluster_ids[i % len(cluster_ids)]
        await client.execute_write(
            _SEED_MEMBER_OF,
            {"node_id": fid, "silo_id": silo_id, "cluster_id": cluster_id},
        )
        edge_count += 1

    node_count = len(claim_ids) + len(fact_ids) + len(cluster_ids)
    return {"nodes": node_count, "edges": edge_count}


async def _count(client: MemgraphClient, query: str, silo_id: str) -> int:
    rows = await client.execute_query(query, {"silo_id": silo_id})
    return int(rows[0]["cnt"]) if rows else 0


async def _get_label_sets(client: MemgraphClient, silo_id: str) -> set[frozenset[str]]:
    rows = await client.execute_query(_GET_LABELS, {"silo_id": silo_id})
    return {frozenset(row["labels"]) for row in rows}


@docker_available
@pytest.mark.integration
class TestSiloPortability:
    async def test_round_trip_node_and_edge_counts_match(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        tmp_path: Path,
    ) -> None:
        """Export then import preserves exact node and edge counts."""
        src_silo = str(unique_silo_id)
        tgt_silo = str(uuid.uuid4())

        try:
            seed_counts = await _seed_silo(memgraph_client, src_silo)
            src_nodes = await _count(memgraph_client, _COUNT_NODES, src_silo)
            src_edges = await _count(memgraph_client, _COUNT_EDGES, src_silo)

            assert src_nodes == seed_counts["nodes"]
            assert src_edges == seed_counts["edges"]

            # Export to temp file
            dump_path = tmp_path / "silo.jsonl"
            with open(dump_path, "w", encoding="utf-8") as f:
                manifest = {
                    "_manifest": {
                        "schema_version": 1,
                        "silo_id": src_silo,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "source_env": "test",
                    }
                }
                f.write(json.dumps(manifest) + "\n")
                await export_nodes(memgraph_client, src_silo, f, page_size=500)
                await export_edges(memgraph_client, src_silo, f, page_size=500)

            # Parse dump to collect element-ID -> record mapping
            with open(dump_path, encoding="utf-8") as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]

            node_records = [ln for ln in lines if ln.get("kind") == "node"]
            edge_records = [ln for ln in lines if ln.get("kind") == "edge"]

            assert len(node_records) == src_nodes, (
                f"Exported node count {len(node_records)} != seeded {src_nodes}"
            )
            assert len(edge_records) == src_edges, (
                f"Exported edge count {len(edge_records)} != seeded {src_edges}"
            )

            # Import into fresh target silo
            importer = SiloImporter(memgraph_client, tgt_silo, dry_run=False)
            for record in node_records:
                # rewrite silo_id in properties to match target
                record["properties"]["silo_id"] = tgt_silo
                await importer.import_node(record)
            for record in edge_records:
                await importer.import_edge(record)

            tgt_nodes = await _count(memgraph_client, _COUNT_NODES, tgt_silo)
            tgt_edges = await _count(memgraph_client, _COUNT_EDGES, tgt_silo)

            assert tgt_nodes == src_nodes, (
                f"Round-trip node count mismatch: got {tgt_nodes}, want {src_nodes}"
            )
            assert tgt_edges == src_edges, (
                f"Round-trip edge count mismatch: got {tgt_edges}, want {src_edges}"
            )

        finally:
            # Cleanup both silos
            for silo in [src_silo, tgt_silo]:
                await memgraph_client.execute_write(
                    "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
                    {"silo_id": silo},
                )

    async def test_round_trip_label_sets_preserved(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        tmp_path: Path,
    ) -> None:
        """Exported label sets are reproduced faithfully in the target silo."""
        src_silo = str(unique_silo_id)
        tgt_silo = str(uuid.uuid4())

        try:
            await _seed_silo(memgraph_client, src_silo)
            src_label_sets = await _get_label_sets(memgraph_client, src_silo)

            dump_path = tmp_path / "labels.jsonl"
            with open(dump_path, "w", encoding="utf-8") as f:
                manifest = {
                    "_manifest": {
                        "schema_version": 1,
                        "silo_id": src_silo,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "source_env": "test",
                    }
                }
                f.write(json.dumps(manifest) + "\n")
                await export_nodes(memgraph_client, src_silo, f, page_size=500)
                await export_edges(memgraph_client, src_silo, f, page_size=500)

            with open(dump_path, encoding="utf-8") as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]

            importer = SiloImporter(memgraph_client, tgt_silo, dry_run=False)
            for record in lines:
                if record.get("kind") == "node":
                    record["properties"]["silo_id"] = tgt_silo
                    await importer.import_node(record)
                elif record.get("kind") == "edge":
                    await importer.import_edge(record)

            tgt_label_sets = await _get_label_sets(memgraph_client, tgt_silo)

            assert tgt_label_sets == src_label_sets, (
                f"Label set mismatch:\n  src={src_label_sets}\n  tgt={tgt_label_sets}"
            )

        finally:
            for silo in [src_silo, tgt_silo]:
                await memgraph_client.execute_write(
                    "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
                    {"silo_id": silo},
                )

    async def test_import_idempotent(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        tmp_path: Path,
    ) -> None:
        """Running the import twice produces no duplicate nodes or edges."""
        src_silo = str(unique_silo_id)
        tgt_silo = str(uuid.uuid4())

        try:
            await _seed_silo(memgraph_client, src_silo)

            dump_path = tmp_path / "idem.jsonl"
            with open(dump_path, "w", encoding="utf-8") as f:
                manifest = {
                    "_manifest": {
                        "schema_version": 1,
                        "silo_id": src_silo,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "source_env": "test",
                    }
                }
                f.write(json.dumps(manifest) + "\n")
                await export_nodes(memgraph_client, src_silo, f, page_size=500)
                await export_edges(memgraph_client, src_silo, f, page_size=500)

            with open(dump_path, encoding="utf-8") as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]

            # Import twice
            for _ in range(2):
                importer = SiloImporter(memgraph_client, tgt_silo, dry_run=False)
                for record in lines:
                    if record.get("kind") == "node":
                        record["properties"]["silo_id"] = tgt_silo
                        await importer.import_node(record)
                    elif record.get("kind") == "edge":
                        await importer.import_edge(record)

            src_nodes = await _count(memgraph_client, _COUNT_NODES, src_silo)
            src_edges = await _count(memgraph_client, _COUNT_EDGES, src_silo)
            tgt_nodes = await _count(memgraph_client, _COUNT_NODES, tgt_silo)
            tgt_edges = await _count(memgraph_client, _COUNT_EDGES, tgt_silo)

            assert tgt_nodes == src_nodes, (
                f"Idempotency failure: node count {tgt_nodes} != {src_nodes}"
            )
            assert tgt_edges == src_edges, (
                f"Idempotency failure: edge count {tgt_edges} != {src_edges}"
            )

        finally:
            for silo in [src_silo, tgt_silo]:
                await memgraph_client.execute_write(
                    "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
                    {"silo_id": silo},
                )

    async def test_dry_run_does_not_mutate(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        tmp_path: Path,
    ) -> None:
        """dry_run=True produces zero nodes in the target silo."""
        src_silo = str(unique_silo_id)
        tgt_silo = str(uuid.uuid4())

        try:
            await _seed_silo(memgraph_client, src_silo)

            dump_path = tmp_path / "dry.jsonl"
            with open(dump_path, "w", encoding="utf-8") as f:
                manifest = {
                    "_manifest": {
                        "schema_version": 1,
                        "silo_id": src_silo,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "source_env": "test",
                    }
                }
                f.write(json.dumps(manifest) + "\n")
                await export_nodes(memgraph_client, src_silo, f, page_size=500)
                await export_edges(memgraph_client, src_silo, f, page_size=500)

            with open(dump_path, encoding="utf-8") as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]

            importer = SiloImporter(memgraph_client, tgt_silo, dry_run=True)
            for record in lines:
                if record.get("kind") == "node":
                    record["properties"]["silo_id"] = tgt_silo
                    await importer.import_node(record)
                elif record.get("kind") == "edge":
                    await importer.import_edge(record)

            tgt_nodes = await _count(memgraph_client, _COUNT_NODES, tgt_silo)
            assert tgt_nodes == 0, f"dry_run mutated graph: {tgt_nodes} nodes found"

        finally:
            for silo in [src_silo, tgt_silo]:
                await memgraph_client.execute_write(
                    "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
                    {"silo_id": silo},
                )
