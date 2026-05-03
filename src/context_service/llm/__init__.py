"""LLM provider services.

Ported from prototype/app/llm/.
"""

from context_service.llm.anthropic import AnthropicError, AnthropicProvider
from context_service.llm.base import LLMProvider, Usage, robust_json_loads
from context_service.llm.gemini import GeminiError, GeminiProvider
from context_service.llm.openai import OpenAIError, OpenAIProvider
from context_service.llm.vertex_gemini import VertexGeminiError, VertexGeminiProvider


def build_llm_provider(provider: str, model: str | None = None) -> LLMProvider:
    """Factory for LLM providers by name.

    Args:
        provider: One of "anthropic", "openai", "vertex_gemini", "gemini".
        model: Optional model override.

    Returns:
        Configured LLMProvider instance.
    """
    if provider == "anthropic":
        return AnthropicProvider.from_settings(model)
    if provider == "openai":
        return OpenAIProvider.from_settings(model)
    if provider == "vertex_gemini":
        return VertexGeminiProvider.from_settings(model)
    # default: gemini
    from context_service.config.settings import get_settings

    settings = get_settings()
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    return GeminiProvider(
        api_key=api_key,
        model=model or settings.default_llm_model,
    )


__all__ = [
    "LLMProvider",
    "Usage",
    "robust_json_loads",
    "build_llm_provider",
    "VertexGeminiProvider",
    "VertexGeminiError",
    "GeminiProvider",
    "GeminiError",
    "AnthropicProvider",
    "AnthropicError",
    "OpenAIProvider",
    "OpenAIError",
]
