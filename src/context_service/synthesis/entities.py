"""Entity extraction for CITE v2 synthesis pipeline.

Provides pluggable NER backends (LLM, spaCy, disabled) behind a common
async interface. Use ``get_entity_extractor`` to select an implementation
by tier name.
"""

from __future__ import annotations

import abc
import asyncio
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.llm.base import LLMProvider

logger = get_logger(__name__)

__all__ = [
    "DisabledEntityExtractor",
    "Entity",
    "EntityExtractor",
    "LLMEntityExtractor",
    "SpacyEntityExtractor",
    "get_entity_extractor",
]


class Entity(BaseModel):
    """A named entity span extracted from text."""

    name: str
    type: str
    start: int
    end: int


class EntityExtractor(abc.ABC):
    """Abstract base for entity extractors."""

    @abc.abstractmethod
    async def extract(self, text: str) -> list[Entity]:
        """Extract named entities from *text*.

        Returns a list of :class:`Entity` objects with character offsets.
        """


def _load_entity_prompt() -> str:
    """Load entity extraction prompt from config/prompts.yaml."""
    import yaml

    from context_service.config.config_loader import CONFIG_DIR

    path = CONFIG_DIR / "prompts.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return data.get("entity_extraction", {}).get("gemini", {}).get("user", "")


_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["name", "type", "start", "end"],
            },
        }
    },
    "required": ["entities"],
}


class LLMEntityExtractor(EntityExtractor):
    """Entity extractor backed by LLM (Gemini Flash by default)."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider

    def _get_provider(self) -> LLMProvider:
        """Lazy-load provider using configured flash model."""
        if self._provider is None:
            from context_service.config.settings import get_settings
            from context_service.llm import build_litellm_provider

            model = get_settings().llm.flash_model.split(":")[-1]  # strip provider prefix
            self._provider = build_litellm_provider("vertex_gemini", model)
        return self._provider

    async def extract(self, text: str) -> list[Entity]:
        if not text or len(text) < 10:
            return []

        try:
            provider = self._get_provider()
            prompt_template = _load_entity_prompt()
            prompt = prompt_template.format(text=text)
            messages = [{"role": "user", "content": prompt}]

            result, _ = await provider.extract_structured(
                messages, _ENTITY_SCHEMA, max_tokens=1024, timeout=10.0
            )

            entities = []
            for e in result.get("entities", []):
                # ponytail: trust LLM offsets but clamp to text bounds
                start = max(0, e.get("start", 0))
                end = min(len(text), e.get("end", start))
                if start < end:
                    entities.append(
                        Entity(
                            name=e.get("name", ""),
                            type=e.get("type", "OTHER"),
                            start=start,
                            end=end,
                        )
                    )
            return entities
        except Exception as exc:
            logger.warning("llm_entity_extraction_failed", error=str(exc))
            return []


class SpacyEntityExtractor(EntityExtractor):
    """Entity extractor using spaCy ``en_core_web_sm``.

    NER is CPU-bound, so extraction is offloaded to a thread pool
    to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._nlp: Any = None
        try:
            import spacy  # type: ignore[import-not-found]

            self._nlp = spacy.load("en_core_web_sm")
        except Exception:
            logger.warning(
                "spacy_unavailable",
                reason="en_core_web_sm not installed; SpacyEntityExtractor will return empty results",
            )

    def _extract_sync(self, text: str) -> list[Entity]:
        """Synchronous extraction for thread pool execution."""
        doc = self._nlp(text)
        return [
            Entity(name=ent.text, type=ent.label_, start=ent.start_char, end=ent.end_char)
            for ent in doc.ents
        ]

    async def extract(self, text: str) -> list[Entity]:
        if self._nlp is None:
            return []
        return await asyncio.to_thread(self._extract_sync, text)


class DisabledEntityExtractor(EntityExtractor):
    """No-op extractor. Always returns an empty list."""

    async def extract(self, text: str) -> list[Entity]:  # noqa: ARG002
        return []


def get_entity_extractor(tier: str) -> EntityExtractor:
    """Return an :class:`EntityExtractor` for the given *tier*.

    Tiers:
    - ``"llm"`` — Gemini Flash (stubbed)
    - ``"spacy"`` — spaCy en_core_web_sm
    - ``"disabled"`` (or any unknown value) — no-op
    """
    if tier == "llm":
        return LLMEntityExtractor()
    elif tier == "spacy":
        return SpacyEntityExtractor()
    else:
        return DisabledEntityExtractor()
