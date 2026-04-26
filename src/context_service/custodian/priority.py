"""Priority formulas for Custodian task types."""

from __future__ import annotations

import math


def compute_consensus_priority(
    avg_chain_confidence: float,
    avg_heat: float,
    distinct_agent_count: int,
) -> float:
    """Compute priority for consensus_on_chains task type.

    Formula: (1 - avg_confidence) * avg_heat * log(min(distinct_agents, 5) + 1)

    Caps agent diversity contribution at 5 per R16-10 (diminishing returns).
    Self-promotion loop blocked: N self-copies = 1 distinct agent = low priority.
    """
    capped_agents = min(distinct_agent_count, 5)
    confidence_gap = 1.0 - max(0.0, min(1.0, avg_chain_confidence))
    heat_factor = max(0.0, min(1.0, avg_heat))
    agent_factor = math.log(capped_agents + 1)

    return confidence_gap * heat_factor * agent_factor


__all__ = ["compute_consensus_priority"]
