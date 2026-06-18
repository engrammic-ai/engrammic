"""Heat constants and decay multipliers."""

from __future__ import annotations

DEFAULT_HEAT = 0.5

LAYER_DECAY_MULTIPLIERS: dict[str, float] = {
    "Claim": 1.0,
    "Finding": 1.0,
    "Fact": 2.0,
    "Commitment": 3.0,
    "Insight": 4.0,
    "ReasoningChain": 4.0,
}


def get_decay_multiplier(layer: str | None) -> float:
    """Return decay multiplier for a node label. Defaults to 1.0 for unknown labels."""
    if layer is None:
        return 1.0
    return LAYER_DECAY_MULTIPLIERS.get(layer, 1.0)


__all__ = ["DEFAULT_HEAT", "LAYER_DECAY_MULTIPLIERS", "get_decay_multiplier"]
