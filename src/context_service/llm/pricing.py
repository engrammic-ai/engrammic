"""LLM pricing utilities shared across modules."""

from __future__ import annotations

# Pricing table sourced from https://cloud.google.com/vertex-ai/generative-ai/pricing
# as of 2026-06-06. Update when prices change.
MODEL_PRICING_USD_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gemini-3.5-flash": {"input": 0.000075, "output": 0.0003},
    "gemini-3.1-flash-lite": {"input": 0.00005, "output": 0.0002},
    "gemini-3.1-pro": {"input": 0.00125, "output": 0.005},
    "gemini-2.5-flash": {"input": 0.000075, "output": 0.0003},
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.005},
    "text-embedding-004": {"input": 0.00001, "output": 0.0},
    "text-embedding-005": {"input": 0.00001, "output": 0.0},
    "gemini-embedding-001": {"input": 0.00001, "output": 0.0},
    "jina-embeddings-v3": {"input": 0.0, "output": 0.0},
}


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
