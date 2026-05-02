"""Pydantic models for MCP tool inputs/outputs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DecayClass(StrEnum):
    """Memory decay classes per EAG spec."""

    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    DURABLE = "durable"
    PERMANENT = "permanent"


class SourceType(StrEnum):
    """Evidence source types."""

    DOCUMENT = "document"
    USER = "user"
    EXTERNAL = "external"
    AGENT = "agent"


class ObservationType(StrEnum):
    """Meta-observation types."""

    BELIEF_CHANGE = "belief_change"
    CONFIDENCE_SHIFT = "confidence_shift"
    CONTRADICTION = "contradiction"
    UNCERTAINTY = "uncertainty"
    CORRECTION = "correction"
    INSIGHT = "insight"


class RelationshipType(StrEnum):
    """Allowed relationship types for context_link."""

    REFERENCES = "REFERENCES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    RELATED_TO = "RELATED_TO"
    CAUSES = "CAUSES"
    CORROBORATES = "CORROBORATES"


class Layer(StrEnum):
    """EAG cognitive layers."""

    MEMORY = "memory"
    KNOWLEDGE = "knowledge"
    WISDOM = "wisdom"
    INTELLIGENCE = "intelligence"


class SPOClaim(BaseModel):
    """Structured claim: subject-predicate-object."""

    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any] | None = None


class EvidenceRef(BaseModel):
    """Reference to evidence source."""

    ref: str = Field(..., description="node:<uuid> or URI")

    @property
    def is_node_ref(self) -> bool:
        return self.ref.startswith("node:")

    @property
    def is_uri(self) -> bool:
        return (
            self.ref.startswith("http://")
            or self.ref.startswith("https://")
            or self.ref.startswith("file://")
        )

    @property
    def node_id(self) -> str | None:
        if self.is_node_ref:
            return self.ref[5:]
        return None

    @field_validator("ref")
    @classmethod
    def validate_ref_format(cls, v: str) -> str:
        if not (
            v.startswith("node:")
            or v.startswith("http://")
            or v.startswith("https://")
            or v.startswith("file://")
        ):
            raise ValueError(
                "Evidence ref must be node:<uuid> or a URI (http://, https://, file://)"
            )
        return v


class ReasoningStep(BaseModel):
    """A step in a reasoning chain."""

    step: int
    reasoning: str
    confidence: float | None = None


class Crystallization(BaseModel):
    """A claim to extract from reasoning."""

    claim: str | SPOClaim
    confidence: float = 0.8


class QueryFilters(BaseModel):
    """Filters for context_query."""

    model_config = {"extra": "forbid"}

    tags: list[str] | None = None
    source_type: list[SourceType] | None = None
    min_confidence: float | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class ProvenanceStep(BaseModel):
    """A step in provenance chain."""

    node_id: str
    layer: Layer
    relationship: str
    confidence: float


class HistoryEntry(BaseModel):
    """An entry in belief history."""

    node_id: str
    content: str
    valid_from: datetime
    valid_to: datetime | None = None
    superseded_by: str | None = None
    supersession_reason: str | None = None
    confidence: float
