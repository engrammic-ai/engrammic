"""Service layer models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Node:
    """Context node stored in Memgraph."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "context"
    content: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    silo_id: uuid.UUID | None = None
    source_uri: str | None = None
    content_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Silo:
    """Organizational container for context nodes."""

    id: uuid.UUID
    name: str
    org_id: str
    description: str | None = None
    dissolvability: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class ScoredNode:
    """Node with relevance score from lookup."""

    node_id: uuid.UUID
    content: str
    type: str
    silo_id: uuid.UUID
    score: float
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class LookupResult:
    """Result from semantic lookup."""

    nodes: list[ScoredNode]
    silos_searched: list[uuid.UUID]
    total_candidates: int
    query: str


@dataclass
class ScopeContext:
    """Scoping context for multi-tenant operations."""

    org_id: str
    silo_id: uuid.UUID


@dataclass
class QueryResult:
    """A single result from context_query."""

    node_id: uuid.UUID
    layer: str
    content: str
    confidence: float
    relevance_score: float
    summary: str | None = None
    tags: list[str] | None = None
    created_at: datetime | None = None


@dataclass
class GraphNode:
    """A node in graph traversal results."""

    node_id: str
    layer: str
    content: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in graph traversal results."""

    from_node: str
    to_node: str
    relationship: str
    weight: float = 1.0


@dataclass
class GraphResult:
    """Result from graph traversal."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    depth_reached: int
    nodes_visited: int
    edges_traversed: int


def derive_silo_id(org_id: str) -> uuid.UUID:
    """Derive deterministic silo ID from org ID (MVP 1:1 mapping)."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"silo:{org_id}")
