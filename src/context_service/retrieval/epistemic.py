"""Epistemic post-processing hooks for recall pipeline.

Applies epistemic features to FusionRetriever output:
- as_of temporal filtering
- Layer-specific score adjustments
- Lazy synthesis triggers (fire-and-forget)
- Belief candidate hints
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings
from context_service.models.mcp import Layer
from context_service.retrieval.fusion import FusedResult
from context_service.signals.freshness import compute_freshness

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


@dataclass
class EpistemicOptions:
    """Options for epistemic post-processing."""

    as_of: datetime | None = None
    include_synthesis: bool = True
    include_hints: bool = False
    min_confidence: float = 0.0


@dataclass
class RecallHint:
    """Hint suggesting an action based on recall results."""

    hint_type: str  # "belief_candidate" | "chain_continuation"
    message: str
    node_ids: list[str] = field(default_factory=list)
    suggested_action: str | None = None


@dataclass
class EpistemicResult:
    """Result of epistemic post-processing."""

    results: list[FusedResult]
    hints: list[RecallHint] = field(default_factory=list)
    synthesis_pending: bool = False


# Module-level task set to prevent fire-and-forget leaks
_synthesis_tasks: set[asyncio.Task[Any]] = set()


def _fire_and_forget(coro: Any) -> None:
    """Schedule coroutine without leaking task reference."""
    task = asyncio.create_task(coro)
    _synthesis_tasks.add(task)
    task.add_done_callback(_synthesis_tasks.discard)


async def apply_epistemic_pipeline(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    options: EpistemicOptions | None = None,
    llm: LLMProvider | None = None,
    query_embedding: list[float] | None = None,  # noqa: ARG001 - prep for chain hints
) -> EpistemicResult:
    """Apply epistemic post-processing to FusionRetriever results.

    Pipeline:
    1. as_of temporal filter (if options.as_of set)
    2. Confidence filter (if options.min_confidence > 0)
    3. Layer-specific score adjustment
    4. Lazy synthesis trigger (fire-and-forget)
    5. Hint detection (if options.include_hints)
    """
    if options is None:
        options = EpistemicOptions()

    # 1. as_of filter
    if options.as_of:
        results = apply_as_of_filter(results, options.as_of)

    # 2. Confidence filter
    if options.min_confidence > 0:
        results = [r for r in results if (r.confidence or 0) >= options.min_confidence]

    # 3. Layer scoring adjustment
    results = apply_layer_scoring(results)

    # 4. Lazy synthesis (fire-and-forget)
    synthesis_pending = False
    if options.include_synthesis and llm is not None:
        synthesis_pending = await maybe_trigger_synthesis(results, silo_id, store, llm)

    # 5. Hints
    hints: list[RecallHint] = []
    if options.include_hints:
        hints = await detect_hints(results, silo_id, store)

    return EpistemicResult(
        results=results,
        hints=hints,
        synthesis_pending=synthesis_pending,
    )


def apply_as_of_filter(
    results: list[FusedResult],
    as_of: datetime,
) -> list[FusedResult]:
    """Filter results to state valid at as_of time.

    Keeps nodes where:
    - created_at <= as_of
    - valid_to is None OR valid_to > as_of
    """
    filtered = []
    for r in results:
        # Skip if created after as_of
        if r.created_at and r.created_at > as_of:
            continue

        # Skip if superseded before as_of (valid_to in properties)
        valid_to = r.properties.get("valid_to") if r.properties else None
        if valid_to:
            if isinstance(valid_to, str):
                valid_to = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
            if isinstance(valid_to, datetime) and valid_to <= as_of:
                continue

        filtered.append(r)

    return filtered


def apply_layer_scoring(results: list[FusedResult]) -> list[FusedResult]:
    """Adjust RRF scores based on layer semantics.

    - Memory: freshness decay
    - Knowledge: corroboration boost
    - Wisdom: staleness penalty
    - Intelligence: no adjustment

    Modifies rrf_score in place and re-sorts.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    for r in results:
        if not r.layer:
            continue

        layer = r.layer.upper()

        if layer == Layer.MEMORY.value.upper():
            # Freshness decay
            if r.created_at:
                freshness = compute_freshness(
                    r.created_at,
                    now,
                    sigma_days=settings.memory_decay_sigma,
                )
                weight = settings.freshness_weight
                r.rrf_score = r.rrf_score * ((1.0 - weight) + weight * freshness)

        elif layer == Layer.KNOWLEDGE.value.upper():
            # Corroboration boost
            corroboration = r.properties.get("corroboration_count", 0) if r.properties else 0
            if corroboration > 0:
                boost = math.log10(1 + corroboration) * 0.2
                r.rrf_score = r.rrf_score * (1 + boost)

        elif layer == Layer.WISDOM.value.upper():
            # Staleness penalty
            synthesis_state = r.properties.get("synthesis_state") if r.properties else None
            if synthesis_state == "STALE":
                r.rrf_score = r.rrf_score * 0.5

    # Re-sort by adjusted score
    results.sort(key=lambda x: x.rrf_score, reverse=True)
    return results


async def maybe_trigger_synthesis(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    llm: LLMProvider,
) -> bool:
    """Fire-and-forget synthesis for corroborating fact groups (v2).

    Returns True if any synthesis was triggered (synthesis_pending).
    Does NOT block on synthesis completion.
    """
    from context_service.db import queries as q
    from context_service.sage.transactions import SYNTHESIS_THRESHOLD, synthesize_from_facts

    # Filter to Facts only (Knowledge layer)
    fact_ids = [
        r.node_id
        for r in results
        if r.layer and r.layer.upper() == Layer.KNOWLEDGE.value.upper()
    ]

    if len(fact_ids) < SYNTHESIS_THRESHOLD:
        return False

    # Find synthesis candidates among these facts
    candidates = await store.execute_query(
        q.GET_SYNTHESIS_CANDIDATES_FOR_NODES,
        {
            "silo_id": silo_id,
            "node_ids": fact_ids,
            "fact_threshold": SYNTHESIS_THRESHOLD,
            "evidence_threshold": 3,
        },
    )

    if not candidates:
        return False

    synthesis_pending = False
    for candidate in candidates:
        candidate_fact_ids = candidate.get("fact_ids", [])
        if len(candidate_fact_ids) >= SYNTHESIS_THRESHOLD:
            _fire_and_forget(
                synthesize_from_facts(store, candidate_fact_ids, silo_id, llm)
            )
            synthesis_pending = True
            logger.info(
                "synthesis_triggered",
                silo_id=silo_id,
                fact_count=len(candidate_fact_ids),
            )

    return synthesis_pending


async def detect_hints(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
) -> list[RecallHint]:
    """Detect belief candidates (v2).

    Chain continuation hints deferred (requires query_embedding access).
    """
    hints: list[RecallHint] = []

    # Belief candidate hints
    hints.extend(await _detect_belief_candidates(store, results, silo_id))

    return hints


async def _detect_belief_candidates(
    store: HyperGraphStore,
    results: list[FusedResult],
    silo_id: str,
) -> list[RecallHint]:
    """Detect when recalled facts could form a belief (v2)."""
    from context_service.db import queries as q
    from context_service.sage.transactions import SYNTHESIS_THRESHOLD

    fact_ids = [
        r.node_id
        for r in results
        if r.layer and r.layer.upper() == Layer.KNOWLEDGE.value.upper()
    ]

    if len(fact_ids) < SYNTHESIS_THRESHOLD:
        return []

    # Find corroborating groups
    candidates = await store.execute_query(
        q.GET_SYNTHESIS_CANDIDATES_FOR_NODES,
        {
            "silo_id": silo_id,
            "node_ids": fact_ids,
            "fact_threshold": SYNTHESIS_THRESHOLD,
            "evidence_threshold": 3,
        },
    )

    if not candidates:
        return []

    hints = []
    for candidate in candidates:
        predicate = candidate.get("predicate", "unknown")
        fact_count = candidate.get("fact_count", 0)
        candidate_ids = candidate.get("fact_ids", [])

        hints.append(
            RecallHint(
                hint_type="belief_candidate",
                message=f"{fact_count} corroborating facts about '{predicate}'. Consider forming a belief.",
                node_ids=candidate_ids[:5],
                suggested_action=f"decide(decision='...', about={candidate_ids[:3]})",
            )
        )

    return hints
