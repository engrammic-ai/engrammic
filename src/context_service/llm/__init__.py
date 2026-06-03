"""LLM provider services - unified via LiteLLM."""

from context_service.llm.base import LLMProvider, Usage, robust_json_loads
from context_service.llm.litellm_provider import (
    LiteLLMError,
    LiteLLMProvider,
    build_litellm_provider,
)

# Backward-compat aliases for provider classes (all map to LiteLLMProvider)
AnthropicProvider = LiteLLMProvider
GeminiProvider = LiteLLMProvider
OpenAIProvider = LiteLLMProvider
VertexGeminiProvider = LiteLLMProvider


def build_llm_provider(provider: str, model: str | None = None) -> LLMProvider:
    """Factory for LLM providers by name.

    Args:
        provider: One of "anthropic", "openai", "vertex_gemini", "gemini", "ollama".
        model: Optional model override.

    Returns:
        Configured LLMProvider instance.
    """
    return build_litellm_provider(provider, model)


__all__ = [
    "LLMProvider",
    "Usage",
    "robust_json_loads",
    "build_llm_provider",
    "build_litellm_provider",
    "LiteLLMProvider",
    "LiteLLMError",
    # Backward-compat
    "AnthropicProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "VertexGeminiProvider",
]
