"""Retrieval-worthiness classification for recall results."""

from __future__ import annotations

from typing import Any, Literal

from context_service.models.mcp import Layer

# Default per-layer minimum relevance thresholds.
# Results below the threshold for their layer are filtered from recall output.
LAYER_THRESHOLDS: dict[str, float] = {
    Layer.KNOWLEDGE: 0.35,
    Layer.WISDOM: 0.35,
    Layer.MEMORY: 0.25,
    Layer.INTELLIGENCE: 0.25,
}

# Minimum relevance threshold applied when reranking actually ran and wrote back
# its scores.  A zero floor is intentionally avoided: the benchmark includes
# adversarial questions where the correct answer is abstention; returning every
# weak node at score 0.0 would induce hallucination.
RERANK_SCORE_FLOOR: float = 0.05

RetrievalQuality = Literal["high", "partial", "low", "none"]


def _threshold_for_layer(layer: str, overrides: dict[str, float] | None = None) -> float:
    """Return the relevance threshold for the given layer string.

    Per-silo ``overrides`` map layer names to custom thresholds.  Unrecognised
    layers fall back to the memory threshold (most permissive default).
    """
    if overrides and layer in overrides:
        return overrides[layer]
    return LAYER_THRESHOLDS.get(layer, LAYER_THRESHOLDS[Layer.MEMORY])


def classify_quality(avg_score: float) -> RetrievalQuality:
    """Map average relevance score to a quality bucket.

    Buckets:
      high    -- avg > 0.6
      partial -- 0.4 <= avg <= 0.6
      low     -- avg < 0.4 (but at least one result)
      none    -- no results (caller's responsibility to pass avg=0.0 or call
                 with empty results)
    """
    if avg_score > 0.6:
        return "high"
    if avg_score >= 0.4:
        return "partial"
    return "low"


def apply_threshold_filter(
    results: list[dict[str, Any]],
    threshold_overrides: dict[str, float] | None = None,
    min_threshold: float | None = None,
    bypass: bool = False,
    rerank_floor: float | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Filter result dicts by per-layer threshold.

    Each result dict is expected to have ``layer`` and ``relevance_score``
    fields.  Results without a ``relevance_score`` are passed through unchanged
    (they came from a non-search path that has no score).

    When ``rerank_floor`` is provided the per-layer thresholds and
    ``threshold_overrides`` are ignored; every scored result is compared to
    ``rerank_floor`` instead.  ``min_threshold``, when set, can only lower the
    effective floor (it is applied as ``min(rerank_floor, min_threshold)``).
    ``bypass=True`` always returns all results regardless of ``rerank_floor``.

    Returns:
        (kept_results, below_threshold_count)
    """
    if bypass:
        return results, 0
    kept: list[dict[str, Any]] = []
    below = 0
    for r in results:
        score = r.get("relevance_score")
        if score is None:
            # No score available; keep without filtering.
            kept.append(r)
            continue
        if rerank_floor is not None:
            threshold: float = rerank_floor
            if min_threshold is not None:
                threshold = min(rerank_floor, min_threshold)
        else:
            layer = r.get("layer", "memory")
            threshold = _threshold_for_layer(layer, threshold_overrides)
            if min_threshold is not None:
                threshold = min(threshold, min_threshold)
        if score >= threshold:
            kept.append(r)
        else:
            below += 1
    return kept, below


def compute_retrieval_quality(
    kept: list[dict[str, Any]],
    below_threshold: int,
    fallback_used: bool = False,
) -> tuple[RetrievalQuality, str | None]:
    """Compute the retrieval_quality label and optional suggestion string.

    Args:
        kept: Results that passed the threshold filter.
        below_threshold: Number of results that were filtered out.
        fallback_used: True when the reranker itself fell back to passthrough
            scores (error path).  In that case quality is reported as "partial"
            at best so agents are not misled by synthetic 1.0/0.99 scores.

    Returns:
        (quality, suggestion)
    """
    if not kept:
        return (
            "none",
            "No results met the relevance threshold. Try a broader query or contact support to adjust per-silo thresholds.",
        )

    scores: list[float] = [float(s) for r in kept if (s := r.get("relevance_score")) is not None]
    if not scores:
        # Kept results but no scores (e.g. node fetch path) -- treat as high.
        return "high", None

    avg = sum(scores) / len(scores)
    quality = classify_quality(avg)

    # Cap quality at "partial" when reranker fallback was used.
    if fallback_used and quality == "high":
        quality = "partial"

    suggestion: str | None = None
    if quality == "partial":
        suggestion = (
            "Some results have moderate relevance. "
            "Consider refining your query for better precision."
        )
    elif quality == "low":
        suggestion = (
            "Results have low relevance scores. "
            "Try a broader or differently-worded query, or reduce top_k."
        )

    if below_threshold > 0 and quality != "none":
        noun = "result" if below_threshold == 1 else "results"
        note = f"{below_threshold} {noun} were filtered below the relevance threshold."
        suggestion = f"{note} {suggestion}" if suggestion else note

    return quality, suggestion
