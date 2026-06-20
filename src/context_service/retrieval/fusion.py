"""RRF fusion retriever — 4-channel retrieval with RRF fusion.

Runs semantic, BM25, and temporal channels in parallel, then uses semantic
hits as seeds for the PPR graph channel. Results are fused with Reciprocal
Rank Fusion (RRF), then optionally reranked with a cross-encoder.

Formula:
    score(node) = sum over channels: 1 / (k + rank)

where k=60 (default smoothing constant) and rank starts at 1.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from context_service.telemetry.metrics import get_db_pool

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.services.context import ContextService
    from context_service.services.models import ScopeContext

logger = structlog.get_logger(__name__)


@dataclass
class ChannelResult:
    """Ranked node IDs from a single retrieval channel.

    Attributes:
        channel_name: Human-readable identifier for the channel.
        ranked_ids: Node IDs ordered from most to least relevant.
        latency_ms: Wall-clock time for the channel call in milliseconds.
        error: Non-None if the channel failed; contains the error message.
    """

    channel_name: str
    ranked_ids: list[str]
    latency_ms: float
    error: str | None = None


@dataclass
class FusedResult:
    """Single node after RRF fusion across channels.

    Attributes:
        node_id: UUID string of the context node.
        rrf_score: Combined RRF score (sum of 1/(k+rank) contributions).
        channel_contributions: Per-channel RRF score contribution for diagnostics.
        content: Node content text (populated when fetch_content=True).
        layer: Cognitive layer the node belongs to (populated when fetch_content=True).
        confidence: Confidence score of the node (populated when fetch_content=True).
        conflict_status: Conflict status of the node (populated when fetch_content=True).
        created_at: Node creation timestamp (populated when fetch_content=True).
        tags: List of tags associated with the node (populated when fetch_content=True).
        properties: Arbitrary node metadata (valid_to, corroboration_count, synthesis_state).
    """

    node_id: str
    rrf_score: float
    channel_contributions: dict[str, float] = field(default_factory=dict)
    content: str | None = None
    layer: str | None = None
    confidence: float | None = None
    conflict_status: str | None = None
    created_at: datetime | None = None
    tags: list[str] | None = None
    properties: dict[str, Any] = field(default_factory=dict)


class FusionRetriever:
    """Fuses semantic and graph retrieval channels with Reciprocal Rank Fusion.

    Args:
        ctx_svc: ContextService instance providing query() and graph_traversal().
        k: RRF smoothing constant. Default 60 (standard literature value).
        channel_config: Optional dict mapping channel names to enabled state.
            Channels: semantic, bm25, temporal, ppr. All default to True.
    """

    def __init__(
        self,
        ctx_svc: ContextService,
        k: int = 60,
        channel_config: dict[str, bool] | None = None,
    ) -> None:
        self._ctx = ctx_svc
        self._k = k
        self._channel_config: dict[str, bool] = {
            "semantic": True,
            "bm25": True,
            "temporal": True,
            "ppr": True,
            "grep": True,
        }
        if channel_config is not None:
            self._channel_config.update(channel_config)

    async def retrieve(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        *,
        graph_depth: int = 2,  # noqa: ARG002
        layers: list[str] | None = None,
        include_superseded: bool = False,  # noqa: ARG002 - prep for channel passthrough
        filters: Any | None = None,  # noqa: ARG002 - prep for channel passthrough
        fetch_content: bool = False,
    ) -> list[FusedResult]:
        """Run 4-channel retrieval with RRF fusion and optional reranking.

        Runs semantic, BM25, and temporal channels in parallel, then uses
        semantic hits as seeds for the PPR graph channel. Results are fused
        with RRF, then optionally reranked with a cross-encoder.

        Over-fetches (top_k * 2) from each channel before fusion, then returns
        the top_k fused results. Channel errors are handled gracefully — each
        failed channel contributes empty results without aborting the pipeline.

        Args:
            query: Free-text search query.
            scope: Org and silo scoping context.
            top_k: Number of results to return after fusion.
            graph_depth: Maximum BFS depth (unused for PPR, kept for compat).
            layers: Optional layer filter applied to all channels.
            include_superseded: If True, include superseded nodes in results.
            filters: Optional additional query filters.
            fetch_content: If True, batch fetch node content and metadata.

        Returns:
            List of FusedResult ordered by descending rrf_score.
        """
        fetch_k = top_k * 2

        # 1. Run enabled channels in parallel.
        channel_coros = []
        channel_names = []
        if self._channel_config.get("semantic", True):
            channel_coros.append(self._semantic_channel(query, scope, fetch_k, layers))
            channel_names.append("semantic")
        if self._channel_config.get("bm25", True):
            channel_coros.append(self._bm25_channel(query, scope, fetch_k, layers))
            channel_names.append("bm25")
        if self._channel_config.get("temporal", True):
            channel_coros.append(self._temporal_channel(query, scope, fetch_k, layers))
            channel_names.append("temporal")
        if self._channel_config.get("grep", True):
            channel_coros.append(self._grep_channel(query, scope, fetch_k, layers))
            channel_names.append("grep")

        raw_results = (
            await asyncio.gather(*channel_coros, return_exceptions=True) if channel_coros else []
        )

        # Process parallel channel results
        channel_results: list[ChannelResult] = []
        semantic_result: ChannelResult | None = None
        for i, name in enumerate(channel_names):
            raw = raw_results[i]
            if isinstance(raw, BaseException):
                logger.warning(f"{name}_channel_error", error=str(raw))
                result = ChannelResult(name, [], 0.0, str(raw))
            else:
                result = raw
            channel_results.append(result)
            if name == "semantic":
                semantic_result = result
            logger.debug(
                "fusion_channel_complete",
                channel=result.channel_name,
                count=len(result.ranked_ids),
                latency_ms=result.latency_ms,
            )

        # 2. PPR graph channel seeded from semantic hits (if enabled).
        if self._channel_config.get("ppr", True):
            seed_ids = (
                semantic_result.ranked_ids[:20]
                if semantic_result and not semantic_result.error
                else []
            )
            ppr_result: ChannelResult
            try:
                ppr_result = await self._ppr_channel(seed_ids, scope, fetch_k, layers)
            except Exception as exc:
                logger.warning("ppr_channel_error", error=str(exc))
                ppr_result = ChannelResult("ppr", [], 0.0, str(exc))

            logger.debug(
                "fusion_channel_complete",
                channel="ppr",
                count=len(ppr_result.ranked_ids),
                latency_ms=ppr_result.latency_ms,
            )
            channel_results.append(ppr_result)

        # 3. RRF fusion across all channels.
        for result in channel_results:
            if result.error is not None:
                logger.warning(
                    "fusion_channel_error",
                    channel=result.channel_name,
                    error=result.error,
                )

        fused = self._fuse_rrf(channel_results, fetch_k)

        # 4. Optional reranking.
        reranked = await self._rerank(query, fused[:50])

        # 5. Batch fetch content if requested.
        final_results = reranked[:top_k]
        if fetch_content and final_results:
            node_ids = [uuid.UUID(f.node_id) for f in final_results]
            nodes_map = await self._ctx.graph_store.batch_get_nodes(node_ids, str(scope.silo_id))
            for f in final_results:
                node = nodes_map.get(uuid.UUID(f.node_id))
                if node:
                    f.content = node.content
                    f.layer = node.properties.get("layer", node.type)
                    f.confidence = node.properties.get("confidence", 0.0)
                    f.conflict_status = node.properties.get("conflict_status", "none")
                    f.created_at = node.created_at
                    f.tags = list(node.properties.get("tags", []))
                    f.properties = {
                        "valid_to": node.properties.get("valid_to"),
                        "corroboration_count": node.properties.get("corroboration_count", 0),
                        "synthesis_state": node.properties.get("synthesis_state"),
                    }

        # Log per-channel hit counts for diagnostics
        channel_counts = {
            c.channel_name: len(c.ranked_ids) for c in channel_results if c.error is None
        }
        logger.info(
            "fusion_complete",
            query_len=len(query),
            top_k=top_k,
            fused_count=len(final_results),
            channels=[c.channel_name for c in channel_results if c.error is None],
            channel_counts=channel_counts,
        )
        return final_results

    async def _semantic_channel(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Run vector similarity search via ContextService.query().

        Args:
            query: Search query text.
            scope: Org and silo scoping context.
            top_k: Maximum results to fetch.
            layers: Optional layer filter.

        Returns:
            ChannelResult with node IDs ranked by relevance_score descending.
        """
        t0 = time.perf_counter()
        try:
            query_results = await self._ctx.query(
                scope,
                query,
                layers=layers,
                top_k=top_k,
            )
            ranked_ids = [str(r.node_id) for r in query_results]
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="semantic",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="semantic",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _graph_channel(
        self,
        seed_ids: list[str],
        scope: ScopeContext,
        top_k: int,
        graph_depth: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Run graph traversal via ContextService.graph_traversal().

        Seeds the BFS walk from the provided node IDs (top hits from the
        semantic channel). Passing seed_nodes instead of a query string avoids
        a redundant embedding call inside graph_traversal.

        Args:
            seed_ids: Node IDs to use as BFS starting points.
            scope: Org and silo scoping context (silo_id used as string).
            top_k: Maximum nodes to return.
            graph_depth: Maximum BFS traversal depth.
            layers: Optional layer filter.

        Returns:
            ChannelResult with node IDs in traversal order.
        """
        t0 = time.perf_counter()
        try:
            graph_result = await self._ctx.graph_traversal(
                str(scope.silo_id),
                seed_nodes=seed_ids,
                max_depth=graph_depth,
                max_nodes=top_k,
                layers=layers,
            )
            ranked_ids = [
                str(node["node_id"])
                for node in graph_result.nodes
                if node.get("node_id") is not None
            ]
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="graph",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="graph",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _bm25_channel(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Hybrid BM25 + trigram text search via Postgres."""
        if not query.strip():
            return ChannelResult(channel_name="bm25", ranked_ids=[], latency_ms=0.0)

        pool = get_db_pool()
        if pool is None:
            return ChannelResult(
                channel_name="bm25",
                ranked_ids=[],
                latency_ms=0.0,
                error="pg_pool unavailable",
            )

        t0 = time.perf_counter()
        try:
            silo_id = str(scope.silo_id)

            # Hybrid: combine ts_rank (BM25-like) with trigram similarity
            if layers:
                sql = """
                    SELECT id,
                           (0.7 * COALESCE(ts_rank(to_tsvector('english', content),
                                                  plainto_tsquery('english', $1)), 0)
                            + 0.3 * COALESCE(similarity(content, $1), 0)) AS rank
                    FROM nodes
                    WHERE silo_id = $2::uuid
                      AND state = 'ACTIVE'
                      AND layer = ANY($3)
                      AND (
                          to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                          OR similarity(content, $1) > 0.1
                      )
                    ORDER BY rank DESC
                    LIMIT $4
                """
                async with pool.acquire() as conn:
                    rows = await conn.fetch(sql, query, silo_id, layers, top_k)
            else:
                sql = """
                    SELECT id,
                           (0.7 * COALESCE(ts_rank(to_tsvector('english', content),
                                                  plainto_tsquery('english', $1)), 0)
                            + 0.3 * COALESCE(similarity(content, $1), 0)) AS rank
                    FROM nodes
                    WHERE silo_id = $2::uuid
                      AND state = 'ACTIVE'
                      AND (
                          to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                          OR similarity(content, $1) > 0.1
                      )
                    ORDER BY rank DESC
                    LIMIT $3
                """
                async with pool.acquire() as conn:
                    rows = await conn.fetch(sql, query, silo_id, top_k)

            ranked_ids = [str(row["id"]) for row in rows]
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="bm25",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="bm25",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _grep_channel(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,  # noqa: ARG002 - layer filter not yet implemented
    ) -> ChannelResult:
        """Keyword text search via Memgraph text_search.regex_search.

        Searches for each query word independently and ranks results by
        how many words matched (pseudo-trigram behavior). Words can appear
        in any order, unlike the sequential AND pattern.
        """
        if not query.strip():
            return ChannelResult(channel_name="grep", ranked_ids=[], latency_ms=0.0)

        t0 = time.perf_counter()
        try:
            words = re.findall(r"\w+", query.lower())
            # Filter short words and limit to top 5
            words = [w for w in words if len(w) >= 3][:5]
            if not words:
                return ChannelResult(channel_name="grep", ranked_ids=[], latency_ms=0.0)

            # Search for each word independently, count matches per node
            match_counts: dict[str, int] = {}
            silo_id = str(scope.silo_id)

            for word in words:
                pattern = f".*{re.escape(word)}.*"
                cypher = """
                    CALL text_search.regex_search("node_content", $pattern, $limit)
                    YIELD node, score
                    WHERE node.silo_id = $silo_id
                    RETURN node.id AS id
                """
                rows = await self._ctx.graph_store.execute_query(
                    cypher,
                    {"pattern": pattern, "limit": top_k * 4, "silo_id": silo_id},
                )
                for row in rows:
                    node_id = str(row.get("id", ""))
                    if node_id:
                        match_counts[node_id] = match_counts.get(node_id, 0) + 1

            # Rank by match count (more words = higher rank)
            ranked = sorted(match_counts.items(), key=lambda x: -x[1])
            ranked_ids = [node_id for node_id, _ in ranked[:top_k]]

            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="grep",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="grep",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _temporal_channel(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Temporal date-aware retrieval with recency scoring.

        Parses NL temporal markers from query, fetches nodes in that window,
        and ranks by recency using layer-specific half-lives.
        """
        from context_service.config.settings import get_settings
        from context_service.retrieval.temporal import (
            compute_recency_score,
            parse_temporal_query,
        )

        t0 = time.perf_counter()
        settings = get_settings()
        temporal_cfg = settings.retrieval.temporal_channel

        if not temporal_cfg.enabled:
            return ChannelResult(
                channel_name="temporal",
                ranked_ids=[],
                latency_ms=0.0,
            )

        now = datetime.now(UTC)
        tq = parse_temporal_query(query, now=now)

        if not tq.has_constraint:
            return ChannelResult(
                channel_name="temporal",
                ranked_ids=[],
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        try:
            since_us = int(tq.since.timestamp() * 1_000_000) if tq.since else None
            until_us = int(tq.until.timestamp() * 1_000_000) if tq.until else None

            where_parts = ["n.silo_id = $silo_id"]
            params: dict[str, object] = {"silo_id": str(scope.silo_id)}

            if since_us is not None:
                where_parts.append("n.created_at >= $since_us")
                params["since_us"] = since_us
            if until_us is not None:
                where_parts.append("n.created_at <= $until_us")
                params["until_us"] = until_us
            if layers:
                where_parts.append("n.layer IN $layers")
                params["layers"] = layers

            cypher = f"""
            MATCH (n:Node)
            WHERE {" AND ".join(where_parts)}
            RETURN n.id AS node_id, n.created_at AS created_at, n.layer AS layer
            ORDER BY n.created_at DESC
            LIMIT {top_k * 2}
            """

            rows = await self._ctx.graph_store.execute_query(cypher, params)

            scored: list[tuple[str, float]] = []
            for row in rows:
                node_id = row.get("node_id")
                if node_id is None:
                    continue

                raw_ts = row.get("created_at")
                node_layer = row.get("layer") or "knowledge"
                half_life = temporal_cfg.half_life_for_layer(node_layer)

                # Non-Memory layers have no time decay (half_life=None)
                if half_life is None:
                    scored.append((str(node_id), 1.0))
                    continue

                if raw_ts is None:
                    scored.append((str(node_id), 0.0))
                    continue

                if isinstance(raw_ts, (int, float)):
                    created_at = datetime.fromtimestamp(raw_ts / 1_000_000, tz=UTC)
                elif isinstance(raw_ts, datetime):
                    created_at = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=UTC)
                else:
                    scored.append((str(node_id), 0.0))
                    continue

                score = compute_recency_score(created_at, now, half_life)
                scored.append((str(node_id), score))

            scored.sort(key=lambda x: x[1], reverse=True)
            ranked_ids = [node_id for node_id, _ in scored[:top_k]]

            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="temporal",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="temporal",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _ppr_channel(
        self,
        seed_ids: list[str],
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """PPR graph traversal from semantic seeds.

        Fetches 2-hop edges from Memgraph, builds adjacency, runs PPR.
        """
        from context_service.config.settings import get_settings
        from context_service.retrieval.ppr import PersonalizedPageRank

        t0 = time.perf_counter()
        settings = get_settings()
        graph_cfg = settings.graph_channel

        if not graph_cfg.enabled or not seed_ids:
            return ChannelResult(channel_name="ppr", ranked_ids=[], latency_ms=0.0)

        try:
            # Fetch 2-hop edges from seeds
            cypher = """
            UNWIND $seed_ids AS seed
            MATCH (n:Node {id: seed, silo_id: $silo_id})-[r]-(m:Node {silo_id: $silo_id})
            RETURN n.id AS source, m.id AS target, type(r) AS edge_type
            UNION
            UNWIND $seed_ids AS seed
            MATCH (n:Node {id: seed, silo_id: $silo_id})-[r1]-(m1:Node {silo_id: $silo_id})-[r2]-(m2:Node {silo_id: $silo_id})
            RETURN m1.id AS source, m2.id AS target, type(r2) AS edge_type
            """
            rows = await self._ctx.graph_store.execute_query(
                cypher, {"seed_ids": seed_ids, "silo_id": str(scope.silo_id)}
            )

            # Build adjacency with edge weights
            adjacency: dict[str, list[tuple[str, float]]] = {}
            for row in rows:
                source = row.get("source")
                target = row.get("target")
                edge_type = row.get("edge_type", "LINK")
                if source is None or target is None:
                    continue
                weight = graph_cfg.edge_weights.get(edge_type, 1.0)
                adjacency.setdefault(str(source), []).append((str(target), weight))

            if not adjacency:
                return ChannelResult(
                    channel_name="ppr",
                    ranked_ids=seed_ids[:top_k],
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                )

            # Run PPR
            ppr = PersonalizedPageRank(
                damping=graph_cfg.damping,
                max_iterations=graph_cfg.max_iterations,
            )
            scores = ppr.compute(seed_ids=seed_ids, adjacency=adjacency)

            # Filter by layers if specified
            if layers:
                layer_cypher = """
                UNWIND $node_ids AS nid
                MATCH (n:Node {id: nid, silo_id: $silo_id})
                WHERE n.layer IN $layers
                RETURN n.id AS node_id
                """
                layer_rows = await self._ctx.graph_store.execute_query(
                    layer_cypher,
                    {
                        "node_ids": list(scores.keys()),
                        "silo_id": str(scope.silo_id),
                        "layers": layers,
                    },
                )
                valid_ids = {r["node_id"] for r in layer_rows}
                scores = {k: v for k, v in scores.items() if k in valid_ids}

            # Sort and return top_k
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            ranked_ids = [node_id for node_id, _ in ranked[:top_k]]

            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="ppr",
                ranked_ids=ranked_ids,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ChannelResult(
                channel_name="ppr",
                ranked_ids=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _rerank(
        self,
        query: str,
        fused: list[FusedResult],
    ) -> list[FusedResult]:
        """Cross-encoder reranking of fused results.

        Fetches document content for top candidates, scores with cross-encoder,
        and reorders by rerank score. Falls back to RRF order on error.
        """
        from context_service.config.models import load_models_config
        from context_service.config.settings import get_settings
        from context_service.reranking.factory import get_reranker

        settings = get_settings()
        if not settings.cross_encoder.enabled or not fused:
            return fused

        t0 = time.perf_counter()
        try:
            # Get reranker from factory (uses TEI if configured, else LiteLLM)
            models_config = load_models_config()
            reranker = get_reranker(models_config, timeout_seconds=10.0)
            if reranker is None:
                logger.debug("rerank_skip_no_reranker")
                return fused

            # Get node IDs to rerank (up to cross_encoder.top_k)
            node_ids = [f.node_id for f in fused[: settings.cross_encoder.top_k]]

            # Fetch content for these nodes
            cypher = """
            UNWIND $node_ids AS nid
            MATCH (n:Node {id: nid})
            RETURN n.id AS node_id, n.content AS content
            """
            rows = await self._ctx.graph_store.execute_query(cypher, {"node_ids": node_ids})
            id_to_content = {row["node_id"]: row.get("content", "") for row in rows}

            # Prepare for reranking
            documents = []
            valid_ids = []
            for node_id in node_ids:
                content = id_to_content.get(node_id, "")
                if content:
                    documents.append(content[:2000])  # Truncate for efficiency
                    valid_ids.append(node_id)

            if not documents:
                return fused

            # Rerank (TEIReranker is async, wrap if needed)
            rerank_results = await reranker.rerank(
                query=query,
                documents=documents,
                node_ids=valid_ids,
            )

            # Build score lookup
            rerank_scores = {r.node_id: r.score for r in rerank_results}

            # Update fused results with rerank scores and reorder
            max_rerank = max(rerank_scores.values()) if rerank_scores else 1.0
            for f in fused:
                if f.node_id in rerank_scores:
                    f.channel_contributions["rerank"] = rerank_scores[f.node_id]
                    # Boost RRF score by normalized rerank score
                    normalized = rerank_scores[f.node_id] / max_rerank if max_rerank > 0 else 0
                    f.rrf_score = f.rrf_score * (0.5 + 0.5 * normalized)

            # Re-sort by updated score
            fused.sort(key=lambda f: f.rrf_score, reverse=True)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.debug("rerank_complete", latency_ms=latency_ms, count=len(rerank_results))

            return fused
        except Exception as exc:
            logger.warning("rerank_fallback", error=str(exc))
            return fused

    def _fuse_rrf(
        self,
        channel_results: list[ChannelResult],
        top_k: int,
    ) -> list[FusedResult]:
        """Fuse ranked lists from multiple channels with Reciprocal Rank Fusion.

        Skips channels that have errors or empty ranked_ids.

        Args:
            channel_results: Per-channel ranked node ID lists.
            top_k: Number of results to return.

        Returns:
            List of FusedResult sorted by rrf_score descending, capped at top_k.
        """
        scores: dict[str, float] = {}
        contributions: dict[str, dict[str, float]] = {}

        for channel in channel_results:
            if channel.error is not None or not channel.ranked_ids:
                continue
            for rank_0, node_id in enumerate(channel.ranked_ids):
                rank = rank_0 + 1  # 1-indexed
                contrib = 1.0 / (self._k + rank)
                scores[node_id] = scores.get(node_id, 0.0) + contrib
                if node_id not in contributions:
                    contributions[node_id] = {}
                contributions[node_id][channel.channel_name] = contrib

        # Normalize RRF scores to 0-1 range.
        # Theoretical max is num_channels / (k + 1) when a node ranks #1 in all channels.
        num_active_channels = sum(1 for c in channel_results if c.error is None and c.ranked_ids)
        max_theoretical = num_active_channels / (self._k + 1) if num_active_channels > 0 else 1.0

        fused = [
            FusedResult(
                node_id=node_id,
                rrf_score=score / max_theoretical if max_theoretical > 0 else score,
                channel_contributions=contributions.get(node_id, {}),
            )
            for node_id, score in scores.items()
        ]
        fused.sort(key=lambda r: r.rrf_score, reverse=True)
        return fused[:top_k]


_RELATIVE_TIME_PATTERN = re.compile(r"^(\d+)([dwm])$")


def _parse_relative_time(s: str, now: datetime) -> datetime:
    """Parse relative time string or ISO datetime.

    Args:
        s: Time string like "7d", "1w", "30d" or ISO datetime
        now: Reference time for relative calculations

    Returns:
        Parsed datetime

    Raises:
        ValueError: If string cannot be parsed
    """
    match = _RELATIVE_TIME_PATTERN.match(s.strip().lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return now - timedelta(days=value)
        elif unit == "w":
            return now - timedelta(weeks=value)
        elif unit == "m":
            return now - timedelta(days=value * 30)  # approximate month

    # Try ISO format
    try:
        parsed = datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Cannot parse time string: {s!r}") from exc


async def _filter_temporal(
    results: list[FusedResult],
    since: datetime | None,
    until: datetime | None,
    store: HyperGraphStore,
    silo_id: str,
) -> list[FusedResult]:
    """Filter fused results by node creation time.

    Args:
        results: List of FusedResult to filter
        since: Include nodes created at or after this time
        until: Include nodes created at or before this time
        store: Graph store for fetching node timestamps
        silo_id: Silo ID for scoping

    Returns:
        Filtered list of FusedResult (order preserved)
    """
    if not results or (since is None and until is None):
        return results

    node_ids = [r.node_id for r in results]

    # Batch fetch created_at for all nodes
    rows = await store.execute_query(
        """
        UNWIND $node_ids AS nid
        MATCH (n:Node {id: nid, silo_id: $silo_id})
        RETURN n.id AS node_id, n.created_at AS created_at
        """,
        {"node_ids": node_ids, "silo_id": silo_id},
    )

    # Build timestamp lookup
    timestamps: dict[str, datetime | None] = {}
    for row in rows:
        node_id = row["node_id"]
        created_at = row.get("created_at")
        if created_at is not None:
            # Handle Memgraph timestamp (microseconds) or datetime
            if isinstance(created_at, (int, float)):
                timestamps[node_id] = datetime.fromtimestamp(created_at / 1_000_000, tz=UTC)
            elif isinstance(created_at, datetime):
                timestamps[node_id] = created_at
            else:
                timestamps[node_id] = None
        else:
            timestamps[node_id] = None

    # Filter results
    filtered = []
    for result in results:
        ts = timestamps.get(result.node_id)
        if ts is None:
            # Keep nodes without timestamps (don't filter them out)
            filtered.append(result)
            continue

        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue

        filtered.append(result)

    return filtered
