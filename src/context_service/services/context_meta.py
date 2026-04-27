"""Result types for meta-memory service methods."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvenanceStep:
    """A single step in a provenance chain."""

    node_id: str
    layer: str
    relationship: str
    confidence: float


@dataclass
class ProvenanceResult:
    """Result from provenance traversal."""

    chain: list[ProvenanceStep]
    root_sources: list[dict[str, Any]]


@dataclass
class HistoryEntry:
    """A single entry in a belief timeline."""

    node_id: str
    content: str
    valid_from: Any
    valid_to: Any
    confidence: float
    supersession_reason: str | None = None


@dataclass
class HistoryResult:
    """Result from belief history query."""

    timeline: list[HistoryEntry]
    current: dict[str, Any] | None


@dataclass
class ReasoningChainResult:
    """Result from storing a reasoning chain."""

    chain_id: uuid.UUID
    crystallizations_queued: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
