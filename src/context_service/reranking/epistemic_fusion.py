"""Epistemic score fusion: make evidence state survive reranking.

Reranker scores overwrite relevance_score wholesale (context_query
_apply_reranking), which made confidence and conflict state invisible to
final ranking. This module multiplies post-rerank scores by a deterministic
epistemic adjustment and re-sorts. Pure functions only: no I/O, no settings
access, callers pass weights explicitly.

Demotion only. Withholding unresolved conflicts / low confidence remains
the trust gate's job (mcp/tools/trust_gate.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Layers whose nodes carry evidence-derived confidence. Memory freshness and
# heat are already fused upstream in ContextService.query; intelligence has
# no decay semantics by design.
_EVIDENCE_LAYERS = frozenset({"knowledge", "wisdom"})


@dataclass(frozen=True)
class EpistemicAdjustment:
    """Per-result fusion breakdown, surfaced in recall output for transparency."""

    multiplier: float
    confidence_factor: float
    conflict_factor: float

    def to_dict(self) -> dict[str, float]:
        return {
            "multiplier": self.multiplier,
            "confidence_factor": self.confidence_factor,
            "conflict_factor": self.conflict_factor,
        }


def compute_epistemic_adjustment(
    layer: str,
    confidence: float | None,
    conflict_status: str | None,
    *,
    confidence_weight: float,
    conflict_penalty: float,
) -> EpistemicAdjustment:
    """Compute the score multiplier for one result.

    confidence_factor = (1 - w) + w * confidence for knowledge/wisdom layers,
    1.0 otherwise. Missing confidence is treated as 1.0 (never penalize
    absent data, mirroring apply_trust_gate). conflict_factor applies the
    penalty to unresolved contradictions on any layer.
    """
    confidence_factor = 1.0
    if (layer or "").lower() in _EVIDENCE_LAYERS and confidence is not None:
        conf = max(0.0, min(1.0, float(confidence)))
        confidence_factor = (1.0 - confidence_weight) + confidence_weight * conf

    conflict_factor = (
        conflict_penalty if (conflict_status or "none") == "unresolved" else 1.0
    )
    return EpistemicAdjustment(
        multiplier=confidence_factor * conflict_factor,
        confidence_factor=confidence_factor,
        conflict_factor=conflict_factor,
    )


def apply_epistemic_fusion(
    results: list[Any],
    *,
    confidence_weight: float,
    conflict_penalty: float,
) -> dict[str, EpistemicAdjustment]:
    """Scale each result's relevance_score in place and re-sort descending.

    Results are any objects with node_id, layer, confidence, conflict_status,
    and relevance_score attributes (QueryResult in production). Results with
    relevance_score None are left unscored but still sorted (None sorts last).

    Returns adjustments keyed by str(node_id) for breakdown surfacing.
    """
    adjustments: dict[str, EpistemicAdjustment] = {}
    for r in results:
        adj = compute_epistemic_adjustment(
            getattr(r, "layer", "") or "",
            getattr(r, "confidence", None),
            getattr(r, "conflict_status", None),
            confidence_weight=confidence_weight,
            conflict_penalty=conflict_penalty,
        )
        adjustments[str(r.node_id)] = adj
        score = getattr(r, "relevance_score", None)
        if score is not None:
            r.relevance_score = float(score) * adj.multiplier
    results.sort(
        key=lambda r: r.relevance_score if r.relevance_score is not None else -1.0,
        reverse=True,
    )
    return adjustments
