"""Custodian pass: detect semantic supersession within a cluster and
write :SUPERSEDES edges.

This closes the Must-Not-Current gap exposed by the AgentContextBench
composite-rot benchmark. Agents store new observations rather than
calling context_update, so SUPERSEDES chains do not form organically.
This async pass detects supersession post-hoc and materializes the edges.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from context_service.config.logging import get_logger
from context_service.custodian.supersession_parser import (
    build_supersession_prompt,
    parse_supersession_response,
)

logger = get_logger(__name__)


class _LLMClient(Protocol):
    async def complete(self, prompt: str, *, temperature: float | None = None) -> str: ...


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
    llm: _LLMClient,
    store: Any,
    *,
    confidence_threshold: float = 0.75,
    source: str = "custodian",
) -> SupersessionPassResult:
    """Detect + materialize supersession edges within one cluster.

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
    prompt_input = [
        {"id": str(n.id), "content": n.content, "created_at": n.created_at} for n in cluster_nodes
    ]
    prompt = build_supersession_prompt(prompt_input)
    try:
        raw = await llm.complete(prompt, temperature=_SUPERSESSION_TEMPERATURE)
        pairs = parse_supersession_response(raw)
    except Exception as exc:
        logger.warning(
            "Supersession LLM call failed; skipping cluster "
            f"cluster_id={cluster_id} silo_id={silo_id} "
            f"error_type={type(exc).__name__} error={exc}"
        )
        return SupersessionPassResult(
            cluster_id=cluster_id,
            pairs_considered=0,
            edges_written=0,
            pairs_dropped_low_confidence=0,
            pairs_dropped_bad_order=0,
            pairs_dropped_unknown_id=0,
        )

    edges_written = 0
    dropped_low_conf = 0
    dropped_bad_order = 0
    dropped_unknown = 0

    for pair in pairs:
        if pair.confidence < confidence_threshold:
            dropped_low_conf += 1
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
            source=source,
            reason=pair.reason,
        )
        if written:
            edges_written += 1

    return SupersessionPassResult(
        cluster_id=cluster_id,
        pairs_considered=len(pairs),
        edges_written=edges_written,
        pairs_dropped_low_confidence=dropped_low_conf,
        pairs_dropped_bad_order=dropped_bad_order,
        pairs_dropped_unknown_id=dropped_unknown,
    )
