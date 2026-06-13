"""Retrieval-worthiness classification for recall results."""

from __future__ import annotations

from typing import Any, Literal

from context_service.models.mcp import Layer

# Default per-layer minimum relevance thresholds.
# Results below the threshold for their layer are filtered from recall output.
LAYER_THRESHOLDS: dict[str, float] = {
    Layer.KNOWLEDGE: 0.01,
    Layer.WISDOM: 0.01,
    Layer.MEMORY: 0.005,
    Layer.INTELLIGENCE: 0.005,
}

# Minimum relevance threshold applied when reranking actually ran and wrote back
# its scores.  A zero floor is intentionally avoided: the benchmark includes
# adversarial questions where the correct answer is abstention; returning every
# weak node at score 0.0 would induce hallucination.
RERANK_SCORE_FLOOR: float = 0.005

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


def compute_adaptive_threshold(
    results: list[dict[str, Any]],
    alpha: float = 0.7,
    floor: float = 0.2,
    score_key: str = "relevance_score",
) -> tuple[float, float]:
    """Compute score-adaptive threshold tau = alpha * max(scores).

    Based on SmartSearch (arXiv:2603.15599): instead of fixed truncation,
    use a query-dependent threshold proportional to the best score.
    High-confidence queries (max ~0.9) get more results; low-confidence
    queries (max ~0.5) get fewer, reducing noise.

    Args:
        results: Result dicts with relevance_score field
        alpha: Proportion of max score to use as threshold (0.5-0.8 recommended)
        floor: Minimum threshold regardless of alpha calculation
        score_key: Which score field to read (default ``relevance_score``; pass
            ``rerank_score`` to compute the threshold against pre-fusion scores)

    Returns:
        (threshold, max_score) tuple for metrics
    """
    scores: list[float] = []
    for r in results:
        score = r.get(score_key)
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return floor, 0.0
    max_score = max(scores)
    return max(alpha * max_score, floor), max_score


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
    ``rerank_floor`` instead.  ``min_threshold``, when set, raises the
    effective floor (results must score at least this high to be kept).
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
            # Floor and adaptive tau judge reranker calibration ("is this about
            # the query at all"); fusion (epistemic multipliers) shrinks
            # relevance_score and is for ordering only, so threshold against
            # the pre-fusion score when the caller provided one.
            floor_basis = r.get("rerank_score")
            if not isinstance(floor_basis, (int, float)):
                floor_basis = score
            threshold: float = rerank_floor
            if min_threshold is not None:
                threshold = max(rerank_floor, min_threshold)
            if float(floor_basis) >= threshold:
                kept.append(r)
            else:
                below += 1
            continue
        layer = r.get("layer", "memory")
        threshold = _threshold_for_layer(layer, threshold_overrides)
        if min_threshold is not None:
            threshold = max(threshold, min_threshold)
        if score >= threshold:
            kept.append(r)
        else:
            below += 1
    return kept, below


def compute_retrieval_quality(
    kept: list[dict[str, Any]],
    below_threshold: int,
    fallback_used: bool = False,
    score_key: str = "relevance_score",
) -> tuple[RetrievalQuality, str | None]:
    """Compute the retrieval_quality label and optional suggestion string.

    Args:
        kept: Results that passed the threshold filter.
        below_threshold: Number of results that were filtered out.
        fallback_used: True when the reranker itself fell back to passthrough
            scores (error path).  In that case quality is reported as "partial"
            at best so agents are not misled by synthetic 1.0/0.99 scores.
        score_key: Which score field to read when computing the average quality
            score (default ``relevance_score``; pass ``rerank_score`` to judge
            quality against pre-fusion scores).

    Returns:
        (quality, suggestion)
    """
    if not kept:
        return (
            "none",
            "No results met the relevance threshold. Try a broader query or contact support to adjust per-silo thresholds.",
        )

    scores: list[float] = []
    for r in kept:
        s = r.get(score_key)
        if not isinstance(s, (int, float)):
            s = r.get("relevance_score")
        if isinstance(s, (int, float)):
            scores.append(float(s))
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
