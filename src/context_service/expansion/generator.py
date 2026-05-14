"""Doc2Query-style expansion generator.

Given document content, generates predicted search queries a user might type
to find it. The output is a space-separated string suitable for SPLADE
tokenization and appending to the document embedding payload.
"""

from __future__ import annotations

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.llm import LLMProvider, build_llm_provider

logger = get_logger(__name__)

_PROMPT_TEMPLATE = """\
Given the following content, generate 3-5 short search queries that a user \
might type to find this information. Focus on synonyms and alternative phrasings.

Content: {content}

Queries (one per line):"""


class ExpansionGenerator:
    """Generates predicted search queries for a piece of content (Doc2Query).

    Args:
        provider: Optional pre-built LLMProvider. If omitted, one is constructed
                  from settings using ``expansion_llm_provider`` /
                  ``expansion_llm_model``.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider
        self._owns_provider = provider is None

    def _get_provider(self) -> LLMProvider:
        if self._provider is None:
            settings = get_settings()
            model_spec = settings.models.get_model("expansion")
            self._provider = build_llm_provider(model_spec.provider, model_spec.model)
        return self._provider

    async def generate(self, content: str) -> str:
        """Generate predicted queries for *content*.

        Returns a space-separated string of query terms, or an empty string
        on failure (LLM error, empty content, etc.).
        """
        if not content or not content.strip():
            return ""

        prompt = _PROMPT_TEMPLATE.format(content=content.strip())
        messages = [{"role": "user", "content": prompt}]

        try:
            provider = self._get_provider()
            text, _ = await provider.complete(messages, temperature=0.3, max_tokens=256)
        except Exception as exc:
            logger.warning(
                "expansion_generator_failed",
                error=str(exc),
                content_len=len(content),
            )
            return ""

        queries = [line.strip().lstrip("-* ").strip() for line in text.splitlines()]
        queries = [q for q in queries if q]

        return " ".join(queries)

    async def close(self) -> None:
        """Release the underlying HTTP client if we own the provider."""
        if self._owns_provider and self._provider is not None:
            await self._provider.close()
            self._provider = None
