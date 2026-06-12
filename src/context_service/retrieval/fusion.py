"""RRF fusion retriever — semantic-seeded graph channel with RRF fusion.

Runs the semantic (vector) channel first, then uses its top results as seeds
for the graph (BFS) channel. This avoids a redundant embedding call that
graph_traversal would otherwise make when given a raw query string. Results
are fused with Reciprocal Rank Fusion (RRF).

Formula:
    score(node) = sum over channels: 1 / (k + rank)

where k=60 (default smoothing constant) and rank starts at 1.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

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
    """

    node_id: str
    rrf_score: float
    channel_contributions: dict[str, float] = field(default_factory=dict)


class FusionRetriever:
    """Fuses semantic and graph retrieval channels with Reciprocal Rank Fusion.

    Args:
        ctx_svc: ContextService instance providing query() and graph_traversal().
        k: RRF smoothing constant. Default 60 (standard literature value).
    """

    def __init__(self, ctx_svc: ContextService, k: int = 60) -> None:
        self._ctx = ctx_svc
        self._k = k

    async def retrieve(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        *,
        graph_depth: int = 2,
        layers: list[str] | None = None,
    ) -> list[FusedResult]:
        """Run 4-channel retrieval with RRF fusion and reranking.

        Channels:
        1. Semantic (vector similarity)
        2. BM25 (keyword search via Postgres GIN)
        3. Temporal (date-aware recency scoring)
        4. PPR (graph traversal from semantic seeds)

        Over-fetches (top_k * 2) from each channel, fuses with RRF, then
        reranks top 50 candidates with a cross-encoder.

        Args:
            query: Free-text search query.
            scope: Org and silo scoping context.
            top_k: Number of results to return after fusion.
            graph_depth: Maximum BFS depth for the graph channel.
            layers: Optional layer filter applied to all channels.

        Returns:
            List of FusedResult ordered by descending rrf_score.
        """
        fetch_k = top_k * 2

        # 1. Run semantic, BM25, temporal in parallel
        semantic_result, bm25_result, temporal_result = await asyncio.gather(
            self._semantic_channel(query, scope, fetch_k, layers),
            self._bm25_channel(query, scope, fetch_k, layers),
            self._temporal_channel(query, scope, fetch_k, layers),
            return_exceptions=True,
        )

        # Handle exceptions as empty results
        if isinstance(semantic_result, Exception):
            logger.warning("semantic_channel_error", error=str(semantic_result))
            semantic_result = ChannelResult("semantic", [], 0.0, str(semantic_result))
        if isinstance(bm25_result, Exception):
            logger.warning("bm25_channel_error", error=str(bm25_result))
            bm25_result = ChannelResult("bm25", [], 0.0, str(bm25_result))
        if isinstance(temporal_result, Exception):
            logger.warning("temporal_channel_error", error=str(temporal_result))
            temporal_result = ChannelResult("temporal", [], 0.0, str(temporal_result))

        for ch in [semantic_result, bm25_result, temporal_result]:
            logger.debug(
                "fusion_channel_complete",
                channel=ch.channel_name,
                count=len(ch.ranked_ids),
                latency_ms=ch.latency_ms,
            )

        # 2. PPR channel seeds from semantic (sequential dependency)
        seed_ids = semantic_result.ranked_ids[:20] if not semantic_result.error else []
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

        # 3. RRF fusion across all channels
        channel_results = [semantic_result, bm25_result, temporal_result, ppr_result]
        fused = self._fuse_rrf(channel_results, fetch_k)

        # 4. Rerank top candidates
        reranked = await self._rerank(query, fused[:50])

        logger.info(
            "fusion_complete",
            query_len=len(query),
            top_k=top_k,
            fused_count=len(reranked),
            channels=[c.channel_name for c in channel_results if not c.error],
        )

        return reranked[:top_k]

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
        """BM25 keyword search via Postgres GIN index. (Stub - Day 1)"""
        return ChannelResult(channel_name="bm25", ranked_ids=[], latency_ms=0.0)

    async def _temporal_channel(
        self,
        query: str,
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Temporal date-aware retrieval. (Stub - Day 1)"""
        return ChannelResult(channel_name="temporal", ranked_ids=[], latency_ms=0.0)

    async def _ppr_channel(
        self,
        seed_ids: list[str],
        scope: ScopeContext,
        top_k: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """PPR graph traversal from semantic seeds. (Stub - Day 2)"""
        return ChannelResult(channel_name="ppr", ranked_ids=[], latency_ms=0.0)

    async def _rerank(
        self,
        query: str,
        fused: list[FusedResult],
    ) -> list[FusedResult]:
        """Cross-encoder reranking. (Stub - Day 2)"""
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

        fused = [
            FusedResult(
                node_id=node_id,
                rrf_score=score,
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
