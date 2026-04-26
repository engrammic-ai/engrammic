"""Prometheus/OpenTelemetry metric definitions for the Custodian phase."""

from __future__ import annotations

from opentelemetry import metrics

from context_service.config.logging import get_logger

logger = get_logger(__name__)

# Pricing table sourced from https://cloud.google.com/vertex-ai/generative-ai/pricing
# as of 2026-04-05. Update when prices change.
MODEL_PRICING_USD_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.000075, "output": 0.0003},
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.005},
    "text-embedding-004": {"input": 0.00001, "output": 0.0},
    "text-embedding-005": {"input": 0.00001, "output": 0.0},
    "gemini-embedding-001": {"input": 0.00001, "output": 0.0},
    "jina-embeddings-v3": {"input": 0.0, "output": 0.0},
}

_meter = metrics.get_meter("context_service.custodian")

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

_phase_tokens = _meter.create_histogram(
    name="custodian.phase.tokens",
    description="Token usage per Custodian phase",
    unit="tokens",
)

_phase_duration = _meter.create_histogram(
    name="custodian.phase.duration_seconds",
    description="Duration of each Custodian phase in seconds",
    unit="s",
)

_tool_calls = _meter.create_counter(
    name="custodian.tool_calls",
    description="Total Custodian tool calls by tool name and cluster level",
)

_visit_strategy = _meter.create_counter(
    name="custodian.visit.strategy",
    description="Visit strategy decisions by strategy type and cluster level",
)

# UpDownCounter used as a gauge: value tracks current cost per pass.
_pass_cost_usd = _meter.create_up_down_counter(
    name="custodian.pass.cost_usd",
    description="Accumulated cost in USD for a Custodian pass",
    unit="USD",
)

_budget_skipped_visits = _meter.create_counter(
    name="custodian.budget.skipped_visits",
    description="Cluster visits skipped due to pass budget exhaustion",
)

_claim_rejections = _meter.create_counter(
    name="custodian.claim_rejections",
    description="Citation claim rejections by reason",
)

_finalize_budget_ratio = _meter.create_histogram(
    name="custodian.finalize.budget_ratio",
    description="Fraction of pass budget consumed at finalization",
)

_hard_cap_hits = _meter.create_counter(
    name="custodian.hard_cap_hits",
    description="UsageLimitExceeded hits by phase",
)

_early_finalize = _meter.create_counter(
    name="custodian.early_finalize",
    description="Early finalize calls (deep pass short-circuited to stitch)",
)

_pro_escalation_sample = _meter.create_counter(
    name="custodian.pro_escalation_sample",
    description="Pro model escalations by reason (complexity_high, ab_sample)",
)


# ---------------------------------------------------------------------------
# Cost helper
# ---------------------------------------------------------------------------


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for a model call using the pricing table.

    Strips the 'google-vertex:' prefix from pydantic-ai model identifiers
    before lookup. Returns 0.0 for unknown models (graceful degradation).
    """
    short_name = model.removeprefix("google-vertex:")
    pricing = MODEL_PRICING_USD_PER_1K_TOKENS.get(short_name)
    if pricing is None:
        return 0.0
    input_cost = (input_tokens / 1000.0) * pricing["input"]
    output_cost = (output_tokens / 1000.0) * pricing["output"]
    return input_cost + output_cost


# ---------------------------------------------------------------------------
# Record helpers -- all defensive, never raise
# ---------------------------------------------------------------------------


def record_phase_usage(
    phase: str,
    level: str,
    tenant: str,
    model: str,
    tokens: int,
    duration_seconds: float,
) -> None:
    """Record token histogram and duration histogram for a completed phase."""
    try:
        attrs = {"phase": phase, "level": level, "tenant": tenant, "model": model}
        _phase_tokens.record(tokens, attributes=attrs)
        _phase_duration.record(
            duration_seconds,
            attributes={"phase": phase, "level": level},
        )
    except Exception:
        logger.debug("record_phase_usage failed", exc_info=True)


def record_tool_call(tool_name: str, level: str) -> None:
    """Increment the tool_calls counter."""
    try:
        _tool_calls.add(1, attributes={"tool": tool_name, "level": level})
    except Exception:
        logger.debug("record_tool_call failed", exc_info=True)


def record_visit_strategy(strategy: str, level: str) -> None:
    """Increment the visit strategy counter."""
    try:
        _visit_strategy.add(1, attributes={"strategy": strategy, "level": level})
    except Exception:
        logger.debug("record_visit_strategy failed", exc_info=True)


def record_claim_rejection(reason: str) -> None:
    """Increment the claim rejections counter."""
    try:
        _claim_rejections.add(1, attributes={"reason": reason})
    except Exception:
        logger.debug("record_claim_rejection failed", exc_info=True)


def record_budget_skip(pass_id: str) -> None:
    """Increment the budget_skipped_visits counter."""
    try:
        _budget_skipped_visits.add(1, attributes={"pass_id": pass_id})
    except Exception:
        logger.debug("record_budget_skip failed", exc_info=True)


def record_pass_cost(pass_id: str, tenant: str, cost_usd: float) -> None:
    """Add cost_usd to the pass cost gauge (UpDownCounter)."""
    try:
        _pass_cost_usd.add(cost_usd, attributes={"pass_id": pass_id, "tenant": tenant})
    except Exception:
        logger.debug("record_pass_cost failed", exc_info=True)


def record_finalize_ratio(ratio: float) -> None:
    """Record the budget consumption ratio at pass finalization."""
    try:
        _finalize_budget_ratio.record(ratio)
    except Exception:
        logger.debug("record_finalize_ratio failed", exc_info=True)


def record_hard_cap_hit(phase: str) -> None:
    """Increment the hard cap hits counter."""
    try:
        _hard_cap_hits.add(1, attributes={"phase": phase})
    except Exception:
        logger.debug("record_hard_cap_hit failed", exc_info=True)


def record_early_finalize() -> None:
    """Increment the early finalize counter."""
    try:
        _early_finalize.add(1)
    except Exception:
        logger.debug("record_early_finalize failed", exc_info=True)


def record_pro_escalation(reason: str) -> None:
    """Increment the Pro escalation sample counter."""
    try:
        _pro_escalation_sample.add(1, attributes={"reason": reason})
    except Exception:
        logger.debug("record_pro_escalation failed", exc_info=True)


# ---------------------------------------------------------------------------
# Concrete RejectionMetrics implementation
# ---------------------------------------------------------------------------


class CustodianRejectionMetrics:
    """Concrete implementation of the RejectionMetrics protocol backed by OTEL."""

    def increment_claim_rejection(self, reason: object, count: int = 1) -> None:
        """Increment rejection counter; reason.value used when it's a StrEnum."""
        try:
            reason_str = reason.value if hasattr(reason, "value") else str(reason)
            _claim_rejections.add(count, attributes={"reason": reason_str})
        except Exception:
            logger.debug(
                "CustodianRejectionMetrics.increment_claim_rejection failed", exc_info=True
            )


__all__ = [
    "CustodianRejectionMetrics",
    "MODEL_PRICING_USD_PER_1K_TOKENS",
    "compute_cost_usd",
    "record_budget_skip",
    "record_claim_rejection",
    "record_early_finalize",
    "record_finalize_ratio",
    "record_hard_cap_hit",
    "record_pass_cost",
    "record_phase_usage",
    "record_pro_escalation",
    "record_tool_call",
    "record_visit_strategy",
]
