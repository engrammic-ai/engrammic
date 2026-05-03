"""Domain-agnostic engine data models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from context_service.utils.json import dumps

IngestClass = Literal["ephemeral", "standard", "durable", "permanent"]


class Participant(BaseModel):
    """A node's role in a hyperedge."""

    node_id: uuid.UUID
    role: str = Field(min_length=1, max_length=255)


class Node(BaseModel):
    """Any entity in the graph."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str = Field(min_length=1, max_length=255)
    content: str | None = Field(default=None)
    properties: dict[str, Any] = Field(default_factory=dict)
    silo_id: uuid.UUID
    source_uri: str | None = Field(default=None, max_length=1024)
    content_hash: str | None = Field(default=None, max_length=64)
    stale: bool = Field(default=False)
    extraction_status: str | None = Field(default=None)
    version: int = Field(default=1, ge=1)
    label: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime | None = Field(default=None)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = Field(default=None)
    supersedes_id: uuid.UUID | None = Field(default=None)
    ingest_class: IngestClass = Field(default="standard")
    content_class: str = Field(default="default", max_length=64)
    last_reset_at: datetime | None = Field(default=None)
    reclassified_at: datetime | None = Field(default=None)

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: str | None) -> str | None:
        if v is not None and len(v.encode("utf-8")) > 102_400:
            msg = "content exceeds 100KB limit"
            raise ValueError(msg)
        return v

    @field_validator("properties")
    @classmethod
    def validate_properties_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(dumps(v).encode("utf-8")) > 51_200:
            msg = "properties exceeds 50KB limit"
            raise ValueError(msg)
        return v


class BinaryEdge(BaseModel):
    """Two-node relationship (native Memgraph relationship)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str = Field(min_length=1, max_length=255)
    source_id: uuid.UUID
    target_id: uuid.UUID
    silo_id: str | None = Field(default=None)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Causal edge fields (v1.2c)
    inferred: bool | None = Field(
        default=None,
        description="True for transitivity-derived edges, None/False for direct extraction.",
    )
    extraction_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="LLM confidence in the extracted relationship.",
    )
    consensus_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Custodian-validated confidence (set after promotion).",
    )
    inferred_from_edge_ids: list[str] | None = Field(
        default=None,
        description="Source edge IDs for transitivity chain (for invalidation).",
    )
    depth: int | None = Field(
        default=None,
        ge=1,
        description="Hop count for inferred edges (e.g., 2 for A->B->C).",
    )

    @model_validator(mode="after")
    def no_self_loop(self) -> BinaryEdge:
        if self.source_id == self.target_id:
            msg = "self-loop: source_id and target_id must differ"
            raise ValueError(msg)
        return self


class HyperEdge(BaseModel):
    """N-ary relationship with 3+ participants (bipartite in Memgraph)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str = Field(min_length=1, max_length=255)
    participants: list[Participant] = Field(min_length=3, max_length=50)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Silo(BaseModel):
    """Organizational container with traversal permeability."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None)
    org_id: str = Field(min_length=1)
    dissolvability: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubGraph(BaseModel):
    """Result of graph traversal queries."""

    nodes: dict[uuid.UUID, Node]
    binary_edges: list[BinaryEdge] = Field(default_factory=list)
    hyper_edges: list[HyperEdge] = Field(default_factory=list)
    root_id: uuid.UUID
