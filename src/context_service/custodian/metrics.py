"""Prometheus/OpenTelemetry metric definitions for the Custodian phase."""

from __future__ import annotations

from opentelemetry import metrics

from context_service.config.logging import get_logger
from context_service.custodian.rejection_reasons import (
    BusinessRejection,
    CitationRejection,
    StructuralRejection,
)
from context_service.llm.pricing import MODEL_PRICING_USD_PER_1K_TOKENS, compute_cost_usd

logger = get_logger(__name__)

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
    # TODO(2026-Q3): remove this deprecated alias once all dashboards use the
    # three layer-specific counters below.
)

_structural_rejections = _meter.create_counter(
    name="custodian.structural_rejections",
    description="Stage 0 claim rejections by StructuralRejection reason",
)

_citation_rejections = _meter.create_counter(
    name="custodian.citation_rejections",
    description="Stage 2 claim rejections by CitationRejection reason",
)

_business_rejections = _meter.create_counter(
    name="custodian.business_rejections",
    description="Stage 3 claim rejections by BusinessRejection reason",
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


def record_claim_rejection(
    reason: StructuralRejection | CitationRejection | BusinessRejection,
) -> None:
    """Increment the layer-specific rejection counter and the legacy alias."""
    try:
        reason_str = reason.value
        attrs = {"reason": reason_str}
        # Deprecated alias — both emitted until 2026-Q3 removal.
        _claim_rejections.add(1, attributes=attrs)
        if isinstance(reason, StructuralRejection):
            _structural_rejections.add(1, attributes=attrs)
        elif isinstance(reason, CitationRejection):
            _citation_rejections.add(1, attributes=attrs)
        elif isinstance(reason, BusinessRejection):
            _business_rejections.add(1, attributes=attrs)
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

    def increment_claim_rejection(
        self,
        reason: StructuralRejection | CitationRejection | BusinessRejection,
        count: int = 1,
    ) -> None:
        """Increment the layer-specific counter and the deprecated legacy alias."""
        try:
            attrs = {"reason": reason.value}
            # Deprecated alias — both emitted until 2026-Q3 removal.
            _claim_rejections.add(count, attributes=attrs)
            if isinstance(reason, StructuralRejection):
                _structural_rejections.add(count, attributes=attrs)
            elif isinstance(reason, CitationRejection):
                _citation_rejections.add(count, attributes=attrs)
            elif isinstance(reason, BusinessRejection):
                _business_rejections.add(count, attributes=attrs)
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
