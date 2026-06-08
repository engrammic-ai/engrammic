"""RRF fusion retriever — parallel semantic and graph channels.

Runs vector (Qdrant) and graph (Memgraph) retrieval in parallel, then fuses
the ranked lists with Reciprocal Rank Fusion (RRF).

Formula:
    score(node) = sum over channels: 1 / (k + rank)

where k=60 (default smoothing constant) and rank starts at 1.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
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
        """Run both retrieval channels in parallel and fuse results with RRF.

        Over-fetches (top_k * 2) from each channel before fusion, then returns
        the top_k fused results. If one channel errors, the other's results are
        returned ranked as-is (each node receives a contribution only from the
        surviving channel).

        Args:
            query: Free-text search query.
            scope: Org and silo scoping context.
            top_k: Number of results to return after fusion.
            graph_depth: Maximum BFS depth for the graph channel.
            layers: Optional layer filter applied to both channels.

        Returns:
            List of FusedResult ordered by descending rrf_score.
        """
        fetch_k = top_k * 2

        semantic_coro = self._semantic_channel(query, scope, fetch_k, layers)
        graph_coro = self._graph_channel(query, scope, fetch_k, graph_depth, layers)

        results = await asyncio.gather(semantic_coro, graph_coro, return_exceptions=True)

        channel_results: list[ChannelResult] = []
        for i, result in enumerate(results):
            channel_name = "semantic" if i == 0 else "graph"
            if isinstance(result, BaseException):
                logger.warning(
                    "fusion_channel_error",
                    channel=channel_name,
                    error=str(result),
                )
                channel_results.append(
                    ChannelResult(
                        channel_name=channel_name,
                        ranked_ids=[],
                        latency_ms=0.0,
                        error=str(result),
                    )
                )
            else:
                channel_results.append(result)
                logger.debug(
                    "fusion_channel_complete",
                    channel=channel_name,
                    count=len(result.ranked_ids),
                    latency_ms=result.latency_ms,
                )

        fused = self._fuse_rrf(channel_results, top_k)

        logger.info(
            "fusion_complete",
            query_len=len(query),
            top_k=top_k,
            fused_count=len(fused),
            channels=[c.channel_name for c in channel_results if c.error is None],
        )
        return fused

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
        query: str,
        scope: ScopeContext,
        top_k: int,
        graph_depth: int,
        layers: list[str] | None,
    ) -> ChannelResult:
        """Run graph traversal via ContextService.graph_traversal().

        Seeds the BFS walk from the top semantic matches (done internally by
        graph_traversal when a query is provided).

        Args:
            query: Semantic seed query.
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
                query=query,
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
