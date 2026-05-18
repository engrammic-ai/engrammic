"""Source tier resolution service.

Determines the quality tier of evidence references by checking, in order:
  1. Evidence node inheritance (node:<id> with source_tier property)
  2. Per-silo rules (silo_source_rules table, silo_id = <silo>)
  3. Global defaults (silo_source_rules table, silo_id IS NULL)
  4. Agent hint (caller-supplied fallback)
  5. Unknown (hardcoded final fallback)

All evidence refs are checked; the highest tier across all matches is returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import text

from context_service.db.postgres import get_session

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class SourceTier(StrEnum):
    """Quality tier for evidence sources."""

    AUTHORITATIVE = "authoritative"
    VALIDATED = "validated"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


_TIER_RANK: dict[SourceTier, int] = {
    SourceTier.AUTHORITATIVE: 4,
    SourceTier.VALIDATED: 3,
    SourceTier.COMMUNITY: 2,
    SourceTier.UNKNOWN: 1,
}


@dataclass(slots=True)
class SourceRule:
    """A single pattern-to-tier mapping rule from silo_source_rules."""

    pattern: str
    tier: str
    silo_id: str | None
    priority: int


async def get_source_rules(silo_id: str | UUID) -> list[SourceRule]:
    """Fetch rules for this silo plus global rules, ordered highest-priority first.

    Silo-specific rules are returned before global rules (silo_id IS NOT NULL
    sorts first). Within each group, rules are ordered by priority DESC.

    Args:
        silo_id: The silo UUID (or string) to fetch rules for.

    Returns:
        List of SourceRule ordered by (silo_id IS NOT NULL) DESC, priority DESC.
    """
    silo_id_str = str(silo_id)

    async with get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT pattern, tier, silo_id::text, priority
                FROM silo_source_rules
                WHERE silo_id = :silo_id OR silo_id IS NULL
                ORDER BY (silo_id IS NOT NULL) DESC, priority DESC
                """
            ),
            {"silo_id": silo_id_str},
        )
        rows = result.fetchall()

    rules: list[SourceRule] = []
    for row in rows:
        rules.append(
            SourceRule(
                pattern=row[0],
                tier=row[1],
                silo_id=row[2],
                priority=row[3],
            )
        )

    logger.debug(
        "source_rules.fetched",
        silo_id=silo_id_str,
        count=len(rules),
    )
    return rules


async def batch_get_node_tiers(
    node_ids: list[str],
    silo_id: str | None = None,
    memgraph: HyperGraphStore | None = None,
) -> dict[str, str | None]:
    """Batch fetch source_tier property from evidence nodes in Memgraph.

    Issues a single batched Cypher query to retrieve node source_tier
    properties. When memgraph is not provided, the context service singleton
    is used via a lazy import.

    Args:
        node_ids: List of node IDs (without the "node:" prefix).
        silo_id: Optional silo to scope the lookup. When None, all nodes
            matching the IDs are returned regardless of silo.
        memgraph: Optional HyperGraphStore instance. When None, the context
            service singleton is used.

    Returns:
        Dict mapping node_id -> source_tier string (or None if not set).
    """
    if not node_ids:
        return {}

    if memgraph is None:
        from context_service.mcp.server import get_context_service

        ctx_svc = get_context_service()
        memgraph = ctx_svc._memgraph

    rows = await memgraph.execute_query(
        """
        UNWIND $node_ids AS nid
        MATCH (n {id: nid})
        WHERE n.silo_id = $silo_id OR $silo_id IS NULL
        RETURN n.id AS id, n.source_tier AS source_tier
        """,
        {"node_ids": node_ids, "silo_id": silo_id},
    )

    return {row["id"]: row.get("source_tier") for row in rows}


async def resolve_source_tier(
    silo_id: str | UUID,
    evidence_refs: list[str],
    agent_hint: str | None = None,
) -> tuple[SourceTier, str]:
    """Resolve the highest quality tier across all evidence references.

    Checks all evidence refs and returns the highest tier found along with
    a label identifying which resolution layer produced that result.

    Resolution order (highest tier across all layers wins):
      1. evidence_node  - node:<id> ref with source_tier property in Memgraph
      2. silo_rule      - per-silo pattern rule from silo_source_rules
      3. global_rule    - global pattern rule (silo_id IS NULL) from silo_source_rules
      4. agent_hint     - caller-supplied tier string
      5. fallback       - SourceTier.UNKNOWN

    Args:
        silo_id: The silo context to resolve rules for.
        evidence_refs: List of evidence URI strings (e.g. "https://...", "node:<id>").
        agent_hint: Optional tier string the caller supplies as a fallback.

    Returns:
        (tier, resolution_layer) tuple where resolution_layer is one of:
        "evidence_node", "silo_rule", "global_rule", "agent_hint", "fallback".
    """
    best_tier: SourceTier = SourceTier.UNKNOWN
    best_layer: str = "fallback"

    # Layer 1: Evidence node inheritance
    node_ids = [ref[5:] for ref in evidence_refs if ref.startswith("node:")]
    if node_ids:
        node_tiers = await batch_get_node_tiers(node_ids, silo_id=str(silo_id))
        for node_id, tier_str in node_tiers.items():
            if not tier_str:
                continue
            try:
                node_tier = SourceTier(tier_str)
            except ValueError:
                logger.warning(
                    "source_tier_resolver.unknown_node_tier",
                    node_id=node_id,
                    tier=tier_str,
                )
                continue
            if _TIER_RANK[node_tier] > _TIER_RANK[best_tier]:
                best_tier = node_tier
                best_layer = "evidence_node"

    # Layers 2+3: Silo-specific then global rules
    rules = await get_source_rules(silo_id)

    for ref in evidence_refs:
        if ref.startswith("node:"):
            continue
        for rule in rules:
            if fnmatch(ref, rule.pattern):
                try:
                    rule_tier = SourceTier(rule.tier)
                except ValueError:
                    logger.warning(
                        "source_tier_resolver.unknown_rule_tier",
                        pattern=rule.pattern,
                        tier=rule.tier,
                    )
                    continue
                if _TIER_RANK[rule_tier] > _TIER_RANK[best_tier]:
                    best_tier = rule_tier
                    best_layer = "silo_rule" if rule.silo_id else "global_rule"
                break  # first matching rule per URI wins

    # Return early if we found something above unknown
    if best_tier != SourceTier.UNKNOWN:
        logger.debug(
            "source_tier_resolver.resolved",
            silo_id=str(silo_id),
            tier=best_tier.value,
            layer=best_layer,
            evidence_count=len(evidence_refs),
        )
        return best_tier, best_layer

    # Layer 4: Agent hint
    if agent_hint:
        try:
            hint_tier = SourceTier(agent_hint)
            logger.debug(
                "source_tier_resolver.resolved",
                silo_id=str(silo_id),
                tier=hint_tier.value,
                layer="agent_hint",
                evidence_count=len(evidence_refs),
            )
            return hint_tier, "agent_hint"
        except ValueError:
            logger.warning(
                "source_tier_resolver.invalid_agent_hint",
                agent_hint=agent_hint,
            )

    # Layer 5: Final fallback
    logger.debug(
        "source_tier_resolver.resolved",
        silo_id=str(silo_id),
        tier=SourceTier.UNKNOWN.value,
        layer="fallback",
        evidence_count=len(evidence_refs),
    )
    return SourceTier.UNKNOWN, "fallback"
