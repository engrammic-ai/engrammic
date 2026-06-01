"""Conflict consolidation: resolver, worker, and supporting types.

Implements the deterministic resolution path from Phase 2 spec
(context/specs/2026-06-01-phase2-conflict-consolidation.md).

Design:
- DeterministicResolver scores using tier_weight * log(1+corroboration) * freshness
- LLMResolverStub always defers (placeholder for Phase 7)
- ConsolidationWorker gathers signals, calls resolver, applies result via TX3
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from context_service.sage.confidence import SOURCE_TIER_WEIGHTS
from context_service.sage.transactions import (
    ConflictStatus,
    SupersedeReason,
    supersede,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class ResolutionAction(StrEnum):
    """Actions available after conflict resolution."""

    SUPERSEDE = "supersede"
    DEFER = "defer"


@dataclass
class ConflictSignals:
    """Signals gathered for a conflicting node.

    Used by resolvers to score and rank competing claims.
    """

    node_id: str
    credibility: float
    corroboration_count: int
    created_at: datetime
    agent_id: str
    source_tier: str


@dataclass
class ResolutionResult:
    """Outcome of a resolver decision.

    For DEFER, winner_id and loser_id are None.
    For SUPERSEDE, both are set.
    """

    action: ResolutionAction
    winner_id: str | None
    loser_id: str | None
    rationale: str


class Resolver(Protocol):
    """Protocol for conflict resolvers."""

    def resolve(
        self,
        node_a: ConflictSignals,
        node_b: ConflictSignals,
    ) -> ResolutionResult: ...


def _days_since(created_at: datetime) -> int:
    """Return integer days elapsed since created_at (using UTC now)."""
    now = datetime.now(UTC)
    # Ensure created_at is tz-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    delta = now - created_at
    return max(0, delta.days)


def _score(signals: ConflictSignals) -> float:
    """Compute resolution score for a set of conflict signals.

    Formula: tier_weight * log(1 + corroboration) * freshness
    where freshness = 1 / (1 + days_since(created_at)).
    """
    tier_weight = SOURCE_TIER_WEIGHTS.get(signals.source_tier, SOURCE_TIER_WEIGHTS["unknown"])
    corroboration = max(1, signals.corroboration_count)
    freshness = 1.0 / (1 + _days_since(signals.created_at))
    return tier_weight * math.log(1 + corroboration) * freshness


class DeterministicResolver:
    """Score-based deterministic resolver.

    Always resolves via SUPERSEDE. Higher score wins.

    Tiebreaker:
    - Same agent: newer claim wins (prefer freshest work from same author).
    - Different agents: older claim wins (stability / anchoring effect).

    Final stable tiebreaker: lexicographically smaller node_id wins, so
    resolution is deterministic even when all signals are identical.
    """

    def resolve(
        self,
        node_a: ConflictSignals,
        node_b: ConflictSignals,
    ) -> ResolutionResult:
        score_a = _score(node_a)
        score_b = _score(node_b)

        if math.isclose(score_a, score_b, rel_tol=1e-9, abs_tol=1e-12):
            winner, loser = self._tiebreak(node_a, node_b)
            rationale = f"tie broken by tiebreaker rule (scores {score_a:.6f})"
        elif score_a > score_b:
            winner, loser = node_a, node_b
            rationale = f"higher score: {score_a:.6f} > {score_b:.6f}"
        else:
            winner, loser = node_b, node_a
            rationale = f"higher score: {score_b:.6f} > {score_a:.6f}"

        return ResolutionResult(
            action=ResolutionAction.SUPERSEDE,
            winner_id=winner.node_id,
            loser_id=loser.node_id,
            rationale=rationale,
        )

    def _tiebreak(
        self,
        node_a: ConflictSignals,
        node_b: ConflictSignals,
    ) -> tuple[ConflictSignals, ConflictSignals]:
        """Return (winner, loser) for tied scores.

        Same agent: newer claim (larger created_at) wins.
        Different agents: older claim (smaller created_at) wins (stability).
        Final fallback: lexicographically smaller node_id wins.
        """
        same_agent = node_a.agent_id == node_b.agent_id

        a_ts = node_a.created_at
        b_ts = node_b.created_at
        if a_ts.tzinfo is None:
            a_ts = a_ts.replace(tzinfo=UTC)
        if b_ts.tzinfo is None:
            b_ts = b_ts.replace(tzinfo=UTC)

        if a_ts != b_ts:
            if same_agent:
                # newer wins
                winner = node_a if a_ts > b_ts else node_b
            else:
                # older wins
                winner = node_a if a_ts < b_ts else node_b
            loser = node_b if winner is node_a else node_a
            return winner, loser

        # Fully identical: stable lexicographic tiebreak on node_id
        winner = node_a if node_a.node_id < node_b.node_id else node_b
        loser = node_b if winner is node_a else node_a
        return winner, loser


class LLMResolverStub:
    """LLM resolver stub that always defers.

    Placeholder for Phase 7 integration. Keeps the same interface
    as DeterministicResolver so it can be swapped in via constructor
    injection on ConsolidationWorker.
    """

    def resolve(
        self,
        node_a: ConflictSignals,  # noqa: ARG002
        node_b: ConflictSignals,  # noqa: ARG002
    ) -> ResolutionResult:
        return ResolutionResult(
            action=ResolutionAction.DEFER,
            winner_id=None,
            loser_id=None,
            rationale="deferred to LLM resolver (not yet implemented)",
        )


class ConsolidationWorker:
    """Async worker that processes conflict events.

    Gathers signals for conflicting nodes, calls the resolver,
    and applies the result (supersede or defer).
    """

    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver: Resolver = resolver if resolver is not None else DeterministicResolver()

    async def process_conflict(
        self,
        store: HyperGraphStore,
        node_a_id: str,
        node_b_id: str,
        silo_id: str,
    ) -> ResolutionResult:
        """Process a conflict between two nodes.

        Gathers signals for each node, calls the resolver, and if the
        action is SUPERSEDE applies TX3 and updates conflict_status on
        both nodes.

        Args:
            store: Graph store instance.
            node_a_id: First conflicting node ID.
            node_b_id: Second conflicting node ID.
            silo_id: Tenant isolation ID.

        Returns:
            ResolutionResult describing what was done.
        """
        signals_a, signals_b = await self._gather_signals(store, node_a_id, node_b_id, silo_id)

        result = self._resolver.resolve(signals_a, signals_b)

        if result.action == ResolutionAction.SUPERSEDE and result.winner_id and result.loser_id:
            await supersede(
                store,
                winner_id=result.winner_id,
                loser_id=result.loser_id,
                silo_id=silo_id,
                reason=SupersedeReason.CONTRADICTION,
            )
            await self._set_resolved_status(store, node_a_id, node_b_id, silo_id)

            logger.info(
                "conflict_resolved_supersede",
                winner_id=result.winner_id,
                loser_id=result.loser_id,
                silo_id=silo_id,
                rationale=result.rationale,
            )
        else:
            logger.debug(
                "conflict_deferred",
                node_a_id=node_a_id,
                node_b_id=node_b_id,
                silo_id=silo_id,
                rationale=result.rationale,
            )

        return result

    async def _gather_signals(
        self,
        store: HyperGraphStore,
        node_a_id: str,
        node_b_id: str,
        silo_id: str,
    ) -> tuple[ConflictSignals, ConflictSignals]:
        """Query graph for signals on both conflicting nodes."""
        cypher = """
        MATCH (n {silo_id: $silo_id})
        WHERE n.id IN $node_ids
        RETURN n.id AS id,
               n.properties.credibility AS credibility,
               n.properties.corroboration_count AS corroboration_count,
               n.created_at AS created_at,
               n.properties.created_by AS agent_id,
               n.properties.source_tier AS source_tier
        """
        rows = await store.execute_query(
            cypher,
            {"silo_id": silo_id, "node_ids": [node_a_id, node_b_id]},
        )

        by_id: dict[str, Any] = {r["id"]: r for r in rows}

        def _build(node_id: str) -> ConflictSignals:
            row = by_id.get(node_id, {})
            raw_created_at = row.get("created_at", datetime.now(UTC).isoformat())
            if isinstance(raw_created_at, str):
                created_at = datetime.fromisoformat(raw_created_at)
            else:
                created_at = raw_created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return ConflictSignals(
                node_id=node_id,
                credibility=float(row.get("credibility") or 0.4),
                corroboration_count=int(row.get("corroboration_count") or 1),
                created_at=created_at,
                agent_id=str(row.get("agent_id") or ""),
                source_tier=str(row.get("source_tier") or "unknown"),
            )

        return _build(node_a_id), _build(node_b_id)

    async def _set_resolved_status(
        self,
        store: HyperGraphStore,
        node_a_id: str,
        node_b_id: str,
        silo_id: str,
    ) -> None:
        """Set conflict_status=resolved_supersede on both nodes."""
        cypher = """
        MATCH (n {silo_id: $silo_id})
        WHERE n.id IN $node_ids
        SET n.properties.conflict_status = $status
        """
        await store.execute_write(
            cypher,
            {
                "silo_id": silo_id,
                "node_ids": [node_a_id, node_b_id],
                "status": ConflictStatus.RESOLVED_SUPERSEDE.value,
            },
        )
