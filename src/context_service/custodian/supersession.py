"""Custodian pass: detect semantic supersession within a cluster and
write :SUPERSEDES edges.

This closes the Must-Not-Current gap exposed by the AgentContextBench
composite-rot benchmark. Agents store new observations rather than
calling context_update, so SUPERSEDES chains do not form organically.
This async pass detects supersession post-hoc and materializes the edges.

Supersession detection uses two paths:
1. **Structured path** (SPO claims): When both nodes have subject/predicate/object
   fields, use `primitives.eag.epistemology.supersession.should_supersede` for
   deterministic comparison based on confidence scores.
2. **LLM path** (free-text): When nodes lack SPO structure, fall back to LLM-based
   semantic comparison via prompts.

The structured path is preferred for reproducibility and speed; LLM is the fallback.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from primitives.eag.epistemology.supersession import (
    ContradictionResult,
    FactForSupersession,
    should_supersede,
)

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.custodian.supersession_parser import (
    build_supersession_prompt,
    parse_supersession_response,
)
from context_service.engine.auto_reflection import (
    create_auto_reflection,
    make_supersession_content,
)

logger = get_logger(__name__)


def _has_spo_structure(node: Any) -> bool:
    """Check if a node has subject/predicate/object fields for structured comparison."""
    return (
        hasattr(node, "subject")
        and hasattr(node, "predicate")
        and hasattr(node, "object")
        and node.subject is not None
        and node.predicate is not None
    )


def _to_fact_for_supersession(node: Any) -> FactForSupersession:
    """Convert a node to primitives' FactForSupersession for structured comparison."""
    return FactForSupersession(
        id=str(node.id),
        subject_id=str(node.subject),
        predicate=str(node.predicate),
        object_id=str(node.object) if node.object else None,
        object_literal=str(node.object) if node.object else None,
        confidence=getattr(node, "confidence", 0.5),
    )


@dataclass(frozen=True)
class StructuredSupersessionPair:
    """Result from structured supersession detection."""

    superseding_id: str
    superseded_id: str
    confidence: float
    reason: str


def _would_create_cycle(
    from_id: str,
    to_id: str,
    edge_graph: dict[str, set[str]],
) -> bool:
    """Return True if adding from_id -> to_id would create a cycle.

    Uses DFS reachability: if to_id can already reach from_id, adding the
    edge would close a cycle.
    """
    visited: set[str] = set()
    stack = [to_id]
    while stack:
        node = stack.pop()
        if node == from_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(edge_graph.get(node, set()))
    return False


def detect_structured_supersession(
    nodes: list[Any],
    dominance_threshold: float = 1.2,
) -> list[StructuredSupersessionPair]:
    """Detect supersession among SPO-structured nodes using primitives.

    Compares all pairs of SPO nodes and returns pairs where one supersedes another.
    Only considers nodes that have subject/predicate/object fields.

    Cycle detection: edges that would close a cycle in the supersession graph
    are skipped and logged as warnings. This guards against contradictory
    primitives decisions across three or more nodes where A > B > C > A.
    """
    spo_nodes = [n for n in nodes if _has_spo_structure(n)]
    if len(spo_nodes) < 2:
        return []

    pairs: list[StructuredSupersessionPair] = []
    edge_graph: dict[str, set[str]] = {}

    for i, older in enumerate(spo_nodes):
        for newer in spo_nodes[i + 1 :]:
            # Ensure newer is actually newer by created_at
            if (
                hasattr(older, "created_at")
                and hasattr(newer, "created_at")
                and newer.created_at <= older.created_at
            ):
                older, newer = newer, older

            older_fact = _to_fact_for_supersession(older)
            newer_fact = _to_fact_for_supersession(newer)

            decision = should_supersede(older_fact, newer_fact, dominance_threshold)

            if decision.result == ContradictionResult.NEW_SUPERSEDES_OLD:
                superseding_id = str(newer.id)
                superseded_id = str(older.id)
                if _would_create_cycle(superseding_id, superseded_id, edge_graph):
                    logger.warning(
                        "Skipping supersession edge that would create a cycle: "
                        f"superseding={superseding_id} superseded={superseded_id}"
                    )
                    continue
                edge_graph.setdefault(superseding_id, set()).add(superseded_id)
                pairs.append(
                    StructuredSupersessionPair(
                        superseding_id=superseding_id,
                        superseded_id=superseded_id,
                        confidence=newer_fact.confidence,
                        reason=decision.reason or "structured_supersession",
                    )
                )
            elif decision.result == ContradictionResult.OLD_SUPERSEDES_NEW:
                superseding_id = str(older.id)
                superseded_id = str(newer.id)
                if _would_create_cycle(superseding_id, superseded_id, edge_graph):
                    logger.warning(
                        "Skipping supersession edge that would create a cycle: "
                        f"superseding={superseding_id} superseded={superseded_id}"
                    )
                    continue
                edge_graph.setdefault(superseding_id, set()).add(superseded_id)
                pairs.append(
                    StructuredSupersessionPair(
                        superseding_id=superseding_id,
                        superseded_id=superseded_id,
                        confidence=older_fact.confidence,
                        reason=decision.reason or "structured_supersession",
                    )
                )
            # UNRESOLVED and NO_CONTRADICTION cases: no supersession edge

    return pairs


class _LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, Any]: ...


# Supersession runs with temperature=0 so the same cluster+prompt produces the
# same pair set across benchmark runs. Variance here directly shows up as edge-
# set drift in back-to-back rot benchmarks.
_SUPERSESSION_TEMPERATURE: float = 0.0


@dataclass(frozen=True)
class SupersessionPassResult:
    """Summary of one cluster's supersession pass."""

    cluster_id: str
    pairs_considered: int
    edges_written: int
    pairs_dropped_low_confidence: int
    pairs_dropped_bad_order: int
    pairs_dropped_unknown_id: int


async def run_supersession_pass(
    cluster_id: str,
    cluster_nodes: list[Any],
    silo_id: str,
    llm: _LLMClient | None,
    store: Any,
    *,
    confidence_threshold: float = 0.75,
    source: str = "custodian",
    dominance_threshold: float = 1.2,
) -> SupersessionPassResult:
    """Detect + materialize supersession edges within one cluster.

    Uses two paths:
    1. Structured: SPO nodes compared via primitives (deterministic, fast)
    2. LLM: Free-text nodes compared via prompts (semantic, slower)

    ``cluster_nodes`` is a list of Node-like objects (must have ``id``,
    ``content``, ``created_at``). ``llm.complete`` returns a JSON string.
    ``store.create_supersedes_edge(from_id, to_id, silo_id, valid_from)``
    writes the edge and returns bool for success.
    """
    if not cluster_nodes:
        return SupersessionPassResult(
            cluster_id=cluster_id,
            pairs_considered=0,
            edges_written=0,
            pairs_dropped_low_confidence=0,
            pairs_dropped_bad_order=0,
            pairs_dropped_unknown_id=0,
        )

    node_map: dict[str, Any] = {str(n.id): n for n in cluster_nodes}

    # Phase 1: Structured supersession for SPO nodes
    structured_pairs = detect_structured_supersession(cluster_nodes, dominance_threshold)

    # Phase 2: LLM supersession for non-SPO nodes
    non_spo_nodes = [n for n in cluster_nodes if not _has_spo_structure(n)]
    llm_pairs: list[Any] = []

    if non_spo_nodes and llm is not None:
        prompt_input = [
            {"id": str(n.id), "content": n.content, "created_at": n.created_at}
            for n in non_spo_nodes
        ]
        prompt = build_supersession_prompt(prompt_input)
        try:
            raw, _usage = await llm.complete(prompt, temperature=_SUPERSESSION_TEMPERATURE, max_tokens=2048)
            llm_pairs = parse_supersession_response(raw)
        except Exception as exc:
            logger.warning(
                "Supersession LLM call failed; continuing with structured pairs only "
                f"cluster_id={cluster_id} silo_id={silo_id} "
                f"error_type={type(exc).__name__} error={exc}"
            )

    # Phase 3: Write edges for all detected pairs (structured + LLM)
    edges_written = 0
    dropped_low_conf = 0
    dropped_bad_order = 0
    dropped_unknown = 0
    written_pairs = []

    # Process structured pairs first
    for pair in structured_pairs:
        if pair.confidence < confidence_threshold:
            dropped_low_conf += 1
            continue

        from_node = node_map.get(pair.superseding_id)
        to_node = node_map.get(pair.superseded_id)

        if not from_node or not to_node:
            dropped_unknown += 1
            continue

        written = await store.create_supersedes_edge(
            from_id=uuid.UUID(pair.superseding_id)
            if isinstance(pair.superseding_id, str)
            else pair.superseding_id,
            to_id=uuid.UUID(pair.superseded_id)
            if isinstance(pair.superseded_id, str)
            else pair.superseded_id,
            silo_id=silo_id,
            valid_from=from_node.created_at,
            source=f"{source}:structured",
            reason=pair.reason,
        )
        if written:
            edges_written += 1
            written_pairs.append(pair)

    # Build initial graph from structured pairs that were written
    existing_edges: dict[str, set[str]] = {}
    for pair in written_pairs:
        existing_edges.setdefault(pair.superseding_id, set()).add(pair.superseded_id)

    # Process LLM pairs
    for pair in llm_pairs:
        if pair.confidence < confidence_threshold:
            dropped_low_conf += 1
            continue

        if _would_create_cycle(pair.superseding_id, pair.superseded_id, existing_edges):
            logger.warning(
                "Skipping LLM supersession pair that would create cycle: %s -> %s",
                pair.superseding_id,
                pair.superseded_id,
            )
            continue

        if pair.superseding_id not in node_map or pair.superseded_id not in node_map:
            dropped_unknown += 1
            logger.warning(
                "Supersession pair references unknown node id "
                f"in cluster={cluster_id}: superseding={pair.superseding_id} "
                f"superseded={pair.superseded_id}"
            )
            continue

        from_node = node_map[pair.superseding_id]
        to_node = node_map[pair.superseded_id]

        if from_node.created_at <= to_node.created_at:
            dropped_bad_order += 1
            logger.warning(
                "Supersession pair has reversed timestamp order "
                f"in cluster={cluster_id}: superseding_ts={from_node.created_at} "
                f"superseded_ts={to_node.created_at}"
            )
            continue

        written = await store.create_supersedes_edge(
            from_id=uuid.UUID(pair.superseding_id)
            if isinstance(pair.superseding_id, str)
            else pair.superseding_id,
            to_id=uuid.UUID(pair.superseded_id)
            if isinstance(pair.superseded_id, str)
            else pair.superseded_id,
            silo_id=silo_id,
            valid_from=from_node.created_at,
            source=f"{source}:llm",
            reason=pair.reason,
        )
        if written:
            edges_written += 1
            written_pairs.append(pair)
            existing_edges.setdefault(pair.superseding_id, set()).add(pair.superseded_id)

    # Auto-reflection hook: fire-and-forget per supersession edge written.
    # Iterate only pairs for which an edge was actually written, not dropped pairs.
    # Errors are caught inside create_auto_reflection and only logged.
    _settings = get_settings()
    if _settings.auto_reflect.enabled and _settings.auto_reflect.on_supersession:
        for pair in written_pairs:
            from_node = node_map.get(pair.superseding_id)
            to_node = node_map.get(pair.superseded_id)
            if not from_node or not to_node:
                continue
            content = make_supersession_content(
                old_content=str(to_node.content),
                new_content=str(from_node.content),
                reason=pair.reason,
            )
            await create_auto_reflection(
                store=store,
                observation_type="belief_change",
                content=content,
                about_node_ids=[pair.superseding_id, pair.superseded_id],
                silo_id=silo_id,
            )

    total_pairs = len(structured_pairs) + len(llm_pairs)
    return SupersessionPassResult(
        cluster_id=cluster_id,
        pairs_considered=total_pairs,
        edges_written=edges_written,
        pairs_dropped_low_confidence=dropped_low_conf,
        pairs_dropped_bad_order=dropped_bad_order,
        pairs_dropped_unknown_id=dropped_unknown,
    )
