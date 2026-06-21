"""Entity extraction for CITE v2 synthesis pipeline.

Provides pluggable NER backends (LLM, spaCy, disabled) behind a common
async interface. Use ``get_entity_extractor`` to select an implementation
by tier name.
"""

from __future__ import annotations

import abc
import asyncio
from typing import Any

from pydantic import BaseModel

from context_service.config.logging import get_logger

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


class LLMEntityExtractor(EntityExtractor):
    """Entity extractor backed by Gemini Flash.

    LLM call is stubbed — returns empty list until prompt + parsing are wired.
    """

    async def extract(self, text: str) -> list[Entity]:  # noqa: ARG002
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
            logger.warning("spacy_unavailable", reason="en_core_web_sm not installed; SpacyEntityExtractor will return empty results")

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
