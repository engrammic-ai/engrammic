"""Clustering service for Leiden community detection and hierarchical summaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from primitives.protocols import Layer

from context_service.clustering import queries
from context_service.clustering.models import (
    LEVEL_GAMMA_MAP,
    Cluster,
    ClusteringJob,
    ClusteringStatus,
    ClusterLevel,
)
from context_service.clustering.prompts import (
    CLUSTER_SUMMARY_SCHEMA,
    MAX_CONTENT_LENGTH,
    MAX_MEMBERS_FOR_SUMMARY,
    get_clustering_system_prompt,
    get_clustering_user_template,
)
from context_service.config.logging import get_logger
from context_service.llm.sanitize import escape_for_prompt
from context_service.utils.json import dumps

if TYPE_CHECKING:
    from context_service.clustering.job_store import ClusteringJobStore
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = get_logger(__name__)


class ClusteringService:
    """Service for GraphRAG-style clustering with Leiden community detection."""

    def __init__(
        self,
        memgraph: HyperGraphStore,
        llm: LLMProvider,
        job_store: ClusteringJobStore,
        embedding: Any | None = None,
        cluster_qdrant: Any | None = None,
    ) -> None:
        self._memgraph = memgraph
        self._llm = llm
        self._job_store = job_store
        self._embedding = embedding
        self._cluster_qdrant = cluster_qdrant

    async def run_clustering(
        self,
        silo_id: str,
        job: ClusteringJob,
        target_layers: list[Layer] | None = None,
    ) -> None:
        """Run the full clustering pipeline.

        1. Clear existing clusters
        2. Detect communities at 3 Leiden resolutions
        3. Build hierarchy (Cluster nodes + MEMBER_OF/PART_OF edges)
        4. Generate summaries for each cluster
        5. Run PageRank and update importance scores

        Args:
            silo_id: Silo identifier (storage scope).
            job: ClusteringJob to track status and results.
            target_layers: Cognitive layers to include in clustering. Defaults
                to [Layer.KNOWLEDGE] (Fact + Claim nodes). Pass
                [Layer.MEMORY, Layer.KNOWLEDGE] to include Document/Passage nodes.
        """
        resolved_layers = target_layers if target_layers is not None else [Layer.KNOWLEDGE]
        node_labels = queries.layer_label_list(resolved_layers)

        job.status = ClusteringStatus.RUNNING
        await self._job_store.save(job)

        try:
            await self.clear_clusters(silo_id)

            level_assignments: dict[ClusterLevel, list[dict[str, Any]]] = {}
            for level in ClusterLevel:
                gamma = LEVEL_GAMMA_MAP[level]
                assignments = await self.detect_communities(silo_id, gamma, node_labels=node_labels)
                level_assignments[level] = assignments
                logger.info(
                    "leiden level complete",
                    level=level.value,
                    gamma=gamma,
                    communities=len({a["community_id"] for a in assignments}),
                )

            all_clusters = await self.build_hierarchy(
                silo_id, level_assignments, node_labels=node_labels
            )

            await self.generate_cluster_summaries(silo_id, all_clusters)

            await self.embed_cluster_summaries(silo_id, all_clusters)

            await self.update_importance(silo_id, node_labels=node_labels)

            level_counts: dict[int, int] = {}
            for level_int, clusters in self._group_by_level(all_clusters).items():
                level_counts[level_int] = len(clusters)

            job.status = ClusteringStatus.COMPLETED
            job.level_counts = level_counts
            job.total_clusters = len(all_clusters)
            job.completed_at = datetime.now(UTC)

        except Exception as e:
            job.status = ClusteringStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now(UTC)
            logger.error("clustering job failed", job_id=job.id, error=str(e))

        await self._job_store.save(job)

    async def detect_communities(
        self,
        silo_id: str,
        gamma: float,
        node_labels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run Leiden community detection at a given resolution.

        Args:
            silo_id: Silo identifier (storage scope).
            gamma: Leiden resolution parameter (higher = more communities).
            node_labels: Node labels to include (e.g. ["Fact", "Claim"]). When
                provided, uses the scoped query variant. When None, falls back
                to the legacy unscoped query (all content node types).

        Returns:
            List of {node_id, community_id} assignments.
        """
        if node_labels is not None:
            results = await self._memgraph.execute_query(
                queries.RUN_LEIDEN_SCOPED,
                {"gamma": gamma, "silo_id": silo_id, "node_labels": node_labels},
            )
        else:
            results = await self._memgraph.execute_query(
                queries.RUN_LEIDEN,
                {"gamma": gamma, "silo_id": silo_id},
            )
        return results

    async def build_hierarchy(
        self,
        silo_id: str,
        level_assignments: dict[ClusterLevel, list[dict[str, Any]]],
        node_labels: list[str] | None = None,
    ) -> list[Cluster]:
        """Build cluster hierarchy from Leiden results at multiple resolutions.

        Creates Cluster nodes with MEMBER_OF edges from members and
        PART_OF edges between child and parent clusters.
        """
        now = datetime.now(UTC)
        all_clusters: list[Cluster] = []
        level_clusters: dict[int, dict[int, Cluster]] = {}

        for level in ClusterLevel:
            assignments = level_assignments.get(level, [])
            if not assignments:
                continue

            communities: dict[int, list[str]] = {}
            for a in assignments:
                cid = a["community_id"]
                nid = a["node_id"]
                if nid is None:
                    continue
                communities.setdefault(cid, []).append(nid)

            level_clusters[level.value] = {}

            # Build in-memory cluster objects first so we can reference their IDs below.
            level_cluster_list: list[tuple[int, list[str], Cluster]] = []
            for community_id, node_ids in communities.items():
                cluster = Cluster(
                    id=str(uuid.uuid4()),
                    level=level.value,
                    community_id=community_id,
                    node_count=len(node_ids),
                    created_at=now,
                    updated_at=now,
                )
                level_cluster_list.append((community_id, node_ids, cluster))
                all_clusters.append(cluster)
                level_clusters[level.value][community_id] = cluster

            if not level_cluster_list:
                continue

            # R-006: one UNWIND write for all Cluster nodes in this level.
            await self._memgraph.execute_write(
                queries.BATCH_CREATE_CLUSTERS,
                {
                    "clusters": [
                        {
                            "id": cl.id,
                            "level": cl.level,
                            "community_id": cl.community_id,
                            "key_topics": dumps([]),
                            "node_count": cl.node_count,
                        }
                        for _, _, cl in level_cluster_list
                    ],
                    "silo_id": silo_id,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                },
            )

            for _community_id, node_ids, cluster in level_cluster_list:
                try:
                    if node_labels is not None:
                        member_of_params: dict[str, Any] = {
                            "node_ids": node_ids,
                            "cluster_id": cluster.id,
                            "silo_id": silo_id,
                            "weight": 1.0,
                            "created_at": now.isoformat(),
                            "node_labels": node_labels,
                        }
                        await self._memgraph.execute_write(
                            queries.BATCH_CREATE_MEMBER_OF_SCOPED,
                            member_of_params,
                        )
                    else:
                        await self._memgraph.execute_write(
                            queries.BATCH_CREATE_MEMBER_OF,
                            {
                                "node_ids": node_ids,
                                "cluster_id": cluster.id,
                                "silo_id": silo_id,
                                "weight": 1.0,
                                "created_at": now.isoformat(),
                            },
                        )
                except Exception as e:
                    logger.warning(
                        "failed to batch create MEMBER_OF for cluster",
                        cluster_id=cluster.id,
                        error=str(e),
                        exc_info=True,
                    )

        await self._link_hierarchy(silo_id, level_assignments, level_clusters, now)

        return all_clusters

    async def _link_hierarchy(
        self,
        silo_id: str,
        level_assignments: dict[ClusterLevel, list[dict[str, Any]]],
        level_clusters: dict[int, dict[int, Cluster]],
        now: datetime,
    ) -> None:
        """Create PART_OF edges between cluster levels."""
        level_node_map: dict[int, dict[str, int]] = {}
        for level in ClusterLevel:
            assignments = level_assignments.get(level, [])
            node_map: dict[str, int] = {}
            for a in assignments:
                nid = a.get("node_id")
                if nid is not None:
                    node_map[nid] = a["community_id"]
            level_node_map[level.value] = node_map

        child_parent_pairs = [
            (ClusterLevel.FINE, ClusterLevel.MEDIUM),
            (ClusterLevel.MEDIUM, ClusterLevel.COARSE),
        ]

        for child_level, parent_level in child_parent_pairs:
            child_map = level_node_map.get(child_level.value, {})
            parent_map = level_node_map.get(parent_level.value, {})
            child_clusters_dict = level_clusters.get(child_level.value, {})
            parent_clusters_dict = level_clusters.get(parent_level.value, {})

            if not child_clusters_dict or not parent_clusters_dict:
                continue

            part_of_pairs: list[dict[str, str]] = []
            for child_cid, child_cluster in child_clusters_dict.items():
                child_nodes = [nid for nid, cid in child_map.items() if cid == child_cid]

                parent_votes: dict[int, int] = {}
                for nid in child_nodes:
                    parent_cid = parent_map.get(nid)
                    if parent_cid is not None:
                        parent_votes[parent_cid] = parent_votes.get(parent_cid, 0) + 1

                if not parent_votes:
                    continue

                best_parent_cid = max(parent_votes, key=lambda k: parent_votes[k])
                parent_cluster = parent_clusters_dict.get(best_parent_cid)
                if parent_cluster is None:
                    continue

                part_of_pairs.append({"child_id": child_cluster.id, "parent_id": parent_cluster.id})

            if part_of_pairs:
                try:
                    await self._memgraph.execute_write(
                        queries.BATCH_CREATE_PART_OF,
                        {
                            "pairs": part_of_pairs,
                            "silo_id": silo_id,
                            "created_at": now.isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "failed to batch create PART_OF edges",
                        pair_count=len(part_of_pairs),
                        error=str(e),
                        exc_info=True,
                    )

    async def generate_cluster_summaries(self, silo_id: str, clusters: list[Cluster]) -> None:
        """Generate LLM summaries for each cluster (parallelized with semaphore)."""
        import asyncio

        from context_service.llm.concurrency import with_llm_limit

        sem = asyncio.Semaphore(5)

        async def _summarize(cluster: Cluster) -> dict[str, object] | None:
            async with sem:
                try:
                    members = await self._memgraph.execute_query(
                        queries.GET_CLUSTER_MEMBERS,
                        {"cluster_id": cluster.id, "silo_id": silo_id},
                    )

                    contents: list[str] = []
                    for m in members[:MAX_MEMBERS_FOR_SUMMARY]:
                        node = m.get("n", {})
                        content = node.get("content") or node.get("name") or node.get("description")
                        if content:
                            contents.append(content[:MAX_CONTENT_LENGTH])

                    if not contents:
                        return None

                    content_text = "\n\n".join(f"- {c}" for c in contents)
                    messages = [
                        {"role": "system", "content": get_clustering_system_prompt()},
                        {
                            "role": "user",
                            "content": get_clustering_user_template().format(
                                count=len(contents), content=escape_for_prompt(content_text)
                            ),
                        },
                    ]

                    raw, _usage = await with_llm_limit(
                        self._llm.extract_structured(messages, CLUSTER_SUMMARY_SCHEMA)
                    )
                    cluster.summary = raw.get("summary", "")
                    cluster.key_topics = raw.get("key_topics", [])

                    return {
                        "id": cluster.id,
                        "summary": cluster.summary,
                        "key_topics": dumps(cluster.key_topics),
                    }

                except Exception as e:
                    logger.warning(
                        "failed to generate summary for cluster",
                        cluster_id=cluster.id,
                        error=str(e),
                        exc_info=True,
                    )
                    return None

        results = await asyncio.gather(*[_summarize(c) for c in clusters])
        updates = [r for r in results if r is not None]
        if updates:
            await self._memgraph.execute_write(
                queries.BATCH_UPDATE_CLUSTER_SUMMARIES,
                {
                    "silo_id": silo_id,
                    "updates": updates,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )

    async def update_importance(
        self,
        silo_id: str,
        node_labels: list[str] | None = None,
    ) -> None:
        """Run PageRank and update importance scores on content and Entity vertices."""
        try:
            if node_labels is not None:
                results = await self._memgraph.execute_query(
                    queries.RUN_PAGERANK_SCOPED,
                    {"silo_id": silo_id, "node_labels": node_labels},
                )
            else:
                results = await self._memgraph.execute_query(
                    queries.RUN_PAGERANK, {"silo_id": silo_id}
                )
            updates = [
                {"node_id": r["node_id"], "rank": float(r["rank"])}
                for r in results
                if r.get("node_id") and r.get("rank") is not None
            ]
            if updates:
                await self._memgraph.execute_write(
                    queries.BATCH_UPDATE_NODE_IMPORTANCE,
                    {"updates": updates, "silo_id": silo_id},
                )
            logger.info("updated importance scores", node_count=len(updates))
        except Exception as e:
            logger.warning("pagerank update failed", error=str(e), exc_info=True)

    async def embed_cluster_summaries(self, silo_id: str, clusters: list[Cluster]) -> None:
        """Embed cluster summaries and upsert into the cluster Qdrant collection."""
        if not self._embedding or not self._cluster_qdrant:
            logger.debug("skipping cluster embedding (no embedding service or cluster Qdrant)")
            return

        with_summary = [c for c in clusters if c.summary]
        if not with_summary:
            return

        await self._cluster_qdrant.ensure_cluster_collection(silo_id)

        # Batch to stay within API limits (VertexAI: 250 per request)
        batch_size = 100
        total_embedded = 0
        for i in range(0, len(with_summary), batch_size):
            batch = with_summary[i : i + batch_size]
            texts = [c.summary for c in batch]
            try:
                vectors = await self._embedding.embed(texts)
            except Exception as e:
                logger.warning(
                    "failed to embed cluster summary batch",
                    batch_start=i,
                    batch_end=i + len(batch),
                    error=str(e),
                    exc_info=True,
                )
                continue

            # R-007: one batch upsert call per embedding batch instead of N single calls.
            upsert_items = [
                {
                    "cluster_id": cluster.id,
                    "vector": vector,
                    "level": cluster.level,
                    "node_count": cluster.node_count,
                }
                for cluster, vector in zip(batch, vectors, strict=True)
            ]
            try:
                upserted = await self._cluster_qdrant.batch_upsert_cluster_embeddings(
                    upsert_items, silo_id
                )
                total_embedded += upserted
            except Exception as e:
                logger.warning(
                    "failed to batch upsert cluster embeddings",
                    batch_start=i,
                    batch_end=i + len(batch),
                    error=str(e),
                    exc_info=True,
                )

            if (i + batch_size) % 500 == 0 or i + batch_size >= len(with_summary):
                logger.info(
                    "cluster embedding progress",
                    embedded=total_embedded,
                    total=len(with_summary),
                )

        logger.info(
            "cluster embedding complete",
            embedded=total_embedded,
            total=len(with_summary),
        )

    async def clear_clusters(self, silo_id: str) -> None:
        """Delete all existing clusters and their relationships for this silo."""
        result = await self._memgraph.execute_write(
            queries.DELETE_ALL_CLUSTERS, {"silo_id": silo_id}
        )
        deleted = result[0].get("deleted", 0) if result else 0
        if deleted > 0:
            logger.info("cleared existing clusters", count=deleted)

        if self._cluster_qdrant:
            try:
                await self._cluster_qdrant.delete_cluster_collection(silo_id)
            except Exception as e:
                logger.debug("failed to delete cluster collection", error=str(e))

    async def clear_and_build_hierarchy_atomic(
        self,
        silo_id: str,
        level_assignments: dict[ClusterLevel, list[dict[str, Any]]],
        node_labels: list[str] | None = None,
    ) -> list[Cluster]:
        """Atomic variant of clear_clusters + build_hierarchy.

        Wraps the wipe + recreate in a single bolt transaction so a failure
        between `clear` and the hierarchy writes cannot leave the silo in an
        empty cluster state. Called from the Dagster `leiden_clusters`
        multi_asset body where partial-failure atomicity is required.

        Args:
            silo_id: Silo identifier (storage scope).
            level_assignments: Leiden assignments per ClusterLevel.
            node_labels: Node labels to restrict membership edges to. Defaults
                to ["Fact", "Claim"] (Knowledge layer). Pass None to fall back
                to legacy unscoped behaviour (all content node types).

        Qdrant collection delete is NOT inside the bolt tx (different system)
        and is deferred to `embed_cluster_summaries` which re-creates the
        collection lazily via `ensure_cluster_collection`.
        """
        if node_labels is None:
            node_labels = ["Fact", "Claim"]
        now = datetime.now(UTC)
        all_clusters: list[Cluster] = []
        level_clusters: dict[int, dict[int, Cluster]] = {}

        async with self._memgraph.transaction() as tx:
            delete_result = await tx.run(queries.DELETE_CLUSTERS, silo_id=silo_id)
            delete_records = await delete_result.data()
            deleted = delete_records[0].get("deleted", 0) if delete_records else 0
            if deleted > 0:
                logger.info("cleared existing clusters (atomic tx)", count=deleted)

            for level in ClusterLevel:
                assignments = level_assignments.get(level, [])
                if not assignments:
                    continue

                communities: dict[int, list[str]] = {}
                for a in assignments:
                    cid = a["community_id"]
                    nid = a["node_id"]
                    if nid is None:
                        continue
                    communities.setdefault(cid, []).append(nid)

                level_clusters[level.value] = {}

                for community_id, node_ids in communities.items():
                    cluster = Cluster(
                        id=str(uuid.uuid4()),
                        level=level.value,
                        community_id=community_id,
                        node_count=len(node_ids),
                        created_at=now,
                        updated_at=now,
                    )

                    await tx.run(
                        queries.CREATE_CLUSTER,
                        id=cluster.id,
                        silo_id=silo_id,
                        level=cluster.level,
                        community_id=cluster.community_id,
                        summary=None,
                        key_topics=dumps([]),
                        node_count=cluster.node_count,
                        created_at=now.isoformat(),
                        updated_at=now.isoformat(),
                    )

                    await tx.run(
                        queries.BATCH_CREATE_MEMBER_OF_SCOPED,
                        node_ids=node_ids,
                        cluster_id=cluster.id,
                        silo_id=silo_id,
                        weight=1.0,
                        created_at=now.isoformat(),
                        node_labels=node_labels,
                    )

                    all_clusters.append(cluster)
                    level_clusters[level.value][community_id] = cluster

            level_node_map: dict[int, dict[str, int]] = {}
            for level in ClusterLevel:
                assignments = level_assignments.get(level, [])
                node_map: dict[str, int] = {}
                for a in assignments:
                    nid = a.get("node_id")
                    if nid is not None:
                        node_map[nid] = a["community_id"]
                level_node_map[level.value] = node_map

            child_parent_pairs = [
                (ClusterLevel.FINE, ClusterLevel.MEDIUM),
                (ClusterLevel.MEDIUM, ClusterLevel.COARSE),
            ]

            for child_level, parent_level in child_parent_pairs:
                child_map = level_node_map.get(child_level.value, {})
                parent_map = level_node_map.get(parent_level.value, {})
                child_clusters_dict = level_clusters.get(child_level.value, {})
                parent_clusters_dict = level_clusters.get(parent_level.value, {})

                if not child_clusters_dict or not parent_clusters_dict:
                    continue

                for child_cid, child_cluster in child_clusters_dict.items():
                    child_nodes = [nid for nid, cid in child_map.items() if cid == child_cid]
                    parent_votes: dict[int, int] = {}
                    for nid in child_nodes:
                        parent_cid = parent_map.get(nid)
                        if parent_cid is not None:
                            parent_votes[parent_cid] = parent_votes.get(parent_cid, 0) + 1
                    if not parent_votes:
                        continue
                    best_parent_cid = max(parent_votes, key=lambda k: parent_votes[k])
                    parent_cluster = parent_clusters_dict.get(best_parent_cid)
                    if parent_cluster is None:
                        continue
                    await tx.run(
                        queries.CREATE_PART_OF,
                        child_id=child_cluster.id,
                        parent_id=parent_cluster.id,
                        silo_id=silo_id,
                        created_at=now.isoformat(),
                    )

        return all_clusters

    async def get_cluster(self, silo_id: str, cluster_id: str) -> Cluster | None:
        """Retrieve a cluster by ID."""
        results = await self._memgraph.execute_query(
            queries.GET_CLUSTER,
            {"id": cluster_id, "silo_id": silo_id},
        )
        if not results:
            return None

        node = results[0].get("c")
        if node is None:
            return None

        return Cluster.from_dict(node)

    async def get_cluster_members(self, silo_id: str, cluster_id: str) -> list[dict[str, Any]]:
        """Get all members of a cluster."""
        results = await self._memgraph.execute_query(
            queries.GET_CLUSTER_MEMBERS,
            {"cluster_id": cluster_id, "silo_id": silo_id},
        )
        return results

    async def get_node_clusters(self, silo_id: str, node_id: str) -> list[dict[str, Any]]:
        """Get all clusters a node belongs to."""
        results = await self._memgraph.execute_query(
            queries.GET_NODE_CLUSTERS,
            {"node_id": node_id, "silo_id": silo_id},
        )
        return results

    async def list_clusters(
        self,
        silo_id: str,
        level: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Cluster], int]:
        """List clusters with optional level filter."""
        results = await self._memgraph.execute_query(
            queries.LIST_CLUSTERS,
            {"silo_id": silo_id, "level": level, "limit": limit, "offset": offset},
        )

        clusters: list[Cluster] = []
        for r in results:
            node = r.get("c")
            if node:
                try:
                    clusters.append(Cluster.from_dict(node))
                except Exception as e:
                    logger.warning("failed to parse cluster", error=str(e), exc_info=True)

        count_result = await self._memgraph.execute_query(
            queries.COUNT_CLUSTERS,
            {"silo_id": silo_id, "level": level},
        )
        total = 0
        if count_result and "total" in count_result[0]:
            total = count_result[0]["total"]

        return clusters, total

    @staticmethod
    def _group_by_level(clusters: list[Cluster]) -> dict[int, list[Cluster]]:
        """Group clusters by level."""
        grouped: dict[int, list[Cluster]] = {}
        for c in clusters:
            grouped.setdefault(c.level, []).append(c)
        return grouped
